# -*- coding: utf-8 -*-
# PickTV / PeekPro 小说源 - 顶点小说
# 站点：https://www.wxsy.net
import re
import json
import base64
import urllib.parse

from base.spider import Spider
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as _req
    CURL_CFFI = True
except Exception:
    import requests as _req
    CURL_CFFI = False


class Spider(Spider):
    def getName(self):
        return "顶点小说"

    def init(self, extend=""):
        self.host = "https://www.wxsy.net"
        if CURL_CFFI:
            self.session = _req.Session(impersonate="chrome")
        else:
            self.session = _req.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.host,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        # 不走系统代理：本地 Clash 等代理会导致直连站点超时
        if hasattr(self.session, "trust_env"):
            self.session.trust_env = False
        print(f"[顶点小说] HTTP 引擎: {'curl_cffi' if CURL_CFFI else 'requests'}")
        self.classes = [
            ("1", "玄幻修真"), ("2", "重生穿越"), ("3", "都市小说"),
            ("4", "军史小说"), ("5", "网游小说"), ("6", "科幻小说"),
            ("7", "灵异小说"), ("8", "言情小说"), ("9", "其他小说"),
        ]

    # ---------------- 工具 ----------------
    def _fix_url(self, url):
        if not url:
            return ""
        if url.startswith("http"):
            return url
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return self.host + url
        return self.host + "/" + url

    def _fetch(self, url, timeout=15, data=None):
        last = None
        for attempt in range(1, 4):
            try:
                if data is not None:
                    resp = self.session.post(url, data=data, timeout=timeout)
                else:
                    resp = self.session.get(url, timeout=timeout)
                resp.encoding = "utf-8"
                return resp.text
            except Exception as e:
                last = e
                print(f"[顶点小说] 第{attempt}次失败 {url} -> {e}")
                # curl_cffi 异常（如 CA 加载失败、中文路径问题）时自动回退 requests
                if CURL_CFFI:
                    try:
                        if not hasattr(self, "_req_fallback"):
                            import requests as _rq
                            self._req_fallback = _rq.Session()
                            self._req_fallback.headers.update(self.session.headers)
                            self._req_fallback.trust_env = False
                        if data is not None:
                            resp = self._req_fallback.post(url, data=data, timeout=timeout)
                        else:
                            resp = self._req_fallback.get(url, timeout=timeout)
                        resp.encoding = "utf-8"
                        return resp.text
                    except Exception as e2:
                        last = e2
        print(f"[顶点小说 Fetch Error] {url} -> {last}")
        return ""

    def _og(self, soup, name):
        node = soup.select_one('meta[property="og:%s"]' % name)
        return node.get("content", "").strip() if node else ""

    # ---------------- 首页 / 分类 ----------------
    def homeContent(self, filter=False):
        return {"class": [{"type_id": tid, "type_name": name} for tid, name in self.classes]}

    def _parse_item(self, item):
        a_tag = item.select_one("div.image a[href*='/novel/']") or item.find("a")
        if not a_tag:
            return None
        href = a_tag.get("href", "")
        m = re.search(r"/novel/(\d+)/", href)
        if not m:
            return None
        img = item.select_one("div.image img")
        pic = img.get("src", "") if img else ""
        title_node = item.select_one("dt a")
        title = title_node.get_text(strip=True) if title_node else ""
        author_node = item.select_one("dt span")
        author = author_node.get_text(strip=True) if author_node else ""
        if not title:
            title = a_tag.get_text(strip=True) or a_tag.get("title", "")
        return {
            "vod_id": m.group(1),
            "vod_name": title or ("书籍" + m.group(1)),
            "vod_pic": self._fix_url(pic),
            "vod_remarks": author,
        }

    def homeVideoContent(self):
        html = self._fetch(self.host)
        if not html:
            return {"list": []}
        soup = BeautifulSoup(html, "html.parser")
        videos, seen = [], set()
        for item in soup.select("div.item"):
            book = self._parse_item(item)
            if book and book["vod_id"] not in seen:
                seen.add(book["vod_id"])
                videos.append(book)
        # 补充分区里的书籍链接
        for a in soup.select("a[href*='/novel/']"):
            m = re.search(r"/novel/(\d+)/", a.get("href", ""))
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            videos.append({
                "vod_id": m.group(1),
                "vod_name": a.get_text(strip=True) or ("书籍" + m.group(1)),
                "vod_pic": "",
                "vod_remarks": "",
            })
        return {"list": videos[:40]}

    def categoryContent(self, tid, pg, filter=False, extend=""):
        try:
            pg = int(pg) if pg else 1
        except ValueError:
            pg = 1
        url = f"{self.host}/sort/{tid}/{pg}.html"
        html = self._fetch(url)
        if not html:
            return {"list": []}
        soup = BeautifulSoup(html, "html.parser")
        videos = []
        for item in soup.select("div.item"):
            book = self._parse_item(item)
            if book:
                videos.append(book)
        pagecount = self._pagecount(soup, tid, pg)
        per = max(len(videos), 1)
        return {
            "list": videos,
            "page": pg,
            "pagecount": pagecount,
            "limit": per,
            "total": pagecount * per,
        }

    def _pagecount(self, soup, tid, pg):
        nums = [int(x) for x in re.findall(r"/sort/lastupdate_%s_0_0_(\d+)\.html" % tid, str(soup))]
        if nums:
            return max(nums)
        return pg + 1 if soup.select_one("a[href*='/sort/']") else pg

    # ---------------- 搜索 ----------------
    def searchContent(self, key, quick=False, pg="1"):
        if int(pg or 1) > 1:
            return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}
        try:
            resp = self.session.post(self.host + "/search.html", data={"s": key}, timeout=15)
            resp.encoding = "utf-8"
            html = resp.text
        except Exception as e:
            print(f"[顶点小说 Search Error] {e}")
            return {"list": []}
        soup = BeautifulSoup(html, "html.parser")
        videos = []
        for li in soup.select("ul.txt-list li"):
            a = li.select_one("span.s2 a")
            if not a:
                continue
            m = re.search(r"/novel/(\d+)/", a.get("href", ""))
            if not m:
                continue
            cate = li.select_one("span.s1")
            author = li.select_one("span.s3")
            remark = (cate.get_text(strip=True) if cate else "") + " " + (author.get_text(strip=True) if author else "")
            videos.append({
                "vod_id": m.group(1),
                "vod_name": a.get_text(strip=True),
                "vod_pic": "",
                "vod_remarks": remark.strip(),
            })
        return {"list": videos, "page": 1, "pagecount": 1, "limit": 20, "total": len(videos)}

    # ---------------- 详情 ----------------
    def _collect_chapters(self, soup, chapters):
        uls = soup.select("ul.section-list")
        if not uls:
            return
        ul = uls[-1]  # 章节列表（最后一个；前一个是最新章节）
        for a in ul.select("li a"):
            href = a.get("href", "")
            m = re.search(r"/novel/(\d+)/read_(\d+)\.html", href)
            if not m:
                continue
            cid = int(m.group(2))
            chapters[cid] = (a.get_text(strip=True), self._fix_url(href))

    def _toc(self, book_id):
        chapters = {}
        html = self._fetch(f"{self.host}/novel/{book_id}/")
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        self._collect_chapters(soup, chapters)
        page = 1
        while page <= 30:
            if len(chapters) < 100:
                break
            html2 = self._fetch(f"{self.host}/novel/{book_id}/chapter_{page}.html")
            if not html2:
                break
            soup2 = BeautifulSoup(html2, "html.parser")
            before = len(chapters)
            self._collect_chapters(soup2, chapters)
            if len(chapters) == before:
                break
            sel = soup2.select_one("select")
            total_pages = 0
            if sel:
                total_pages = len([o for o in sel.select("option") if "chapter_" in (o.get("value") or "")])
            if total_pages and total_pages <= page:
                break
            if not sel and len(chapters) >= 100:
                pass  # 没有页码选择器时继续尝试下一页
            page += 1
        return [chapters[k] for k in sorted(chapters.keys())]

    def detailContent(self, ids):
        ids = ids if isinstance(ids, list) else [ids]
        book_id = ids[0]
        m = re.search(r"(\d+)", str(book_id))
        if not m:
            return {}
        book_id = m.group(1)
        html = self._fetch(f"{self.host}/novel/{book_id}/")
        if not html:
            return {}
        soup = BeautifulSoup(html, "html.parser")
        title = self._og(soup, "novel:book_name") or self._og(soup, "title")
        author = self._og(soup, "novel:author")
        pic = self._fix_url(self._og(soup, "image"))
        category = self._og(soup, "novel:category")
        status = self._og(soup, "novel:status")
        desc = self._og(soup, "description") or ""
        desc = re.sub(r"(?:emsp;|nbsp;)+", " ", desc)
        chapters = self._toc(book_id)
        vod_play_url = "#".join([f"{t}${u}" for t, u in chapters])
        return {
            "list": [{
                "vod_id": book_id,
                "vod_name": title or ("书籍" + book_id),
                "vod_pic": pic,
                "vod_author": author,
                "type_name": category,
                "vod_content": f"作者：{author}  {category}  {status}\n\n{desc}",
                "vod_play_from": "顶点小说",
                "vod_play_url": vod_play_url,
            }]
        }

    # ---------------- 章节正文 ----------------
    def playerContent(self, flag, id, vipFlags=None):
        url = id if str(id).startswith("http") else self._fix_url(id)
        try:
            m = re.search(r"read_(\d+)", url)
            base_cid = m.group(1) if m else None
            title = ""
            parts = []
            current = url
            for _ in range(20):
                html = self._fetch(current)
                if not html:
                    break
                soup = BeautifulSoup(html, "html.parser")
                if not title:
                    h3 = soup.select_one(".word_read h3")
                    if h3:
                        title = re.sub(r"[（(]第\d+页[)）]\s*$", "", h3.get_text(strip=True))
                for b64 in re.findall(r"qsbs\.bb\('([^']+)'\)", html):
                    try:
                        raw = base64.b64decode(b64).decode("utf-8", "ignore")
                    except Exception:
                        continue
                    cs = BeautifulSoup(raw, "html.parser")
                    for tag in cs.find_all(["script", "style"]):
                        tag.decompose()
                    text = cs.get_text("\n", strip=True)
                    if text:
                        parts.append(text)
                nxt = ""
                for a in soup.select(".word_read .read_btn a"):
                    if a.get_text(strip=True) == "下一章":
                        nxt = a.get("href", "")
                        break
                if not nxt:
                    break
                nxt = self._fix_url(nxt)
                nm = re.search(r"read_(\d+)_(\d+)\.html", nxt)
                if not nm:
                    break
                if base_cid and nm.group(1) != base_cid:
                    break
                current = nxt
            content = re.sub(r"\n\s*\n+", "\n\n", "\n".join(parts)).strip()
            if not content:
                content = "未获取到章节内容"
            return self._novel_result(title or "章节", content)
        except Exception as e:
            print(f"[顶点小说 playerContent] {e}")
            return self._novel_result("错误", f"发生异常: {e}")

    def _novel_result(self, title, content):
        data = {"title": title, "content": content}
        return {
            "parse": 0,
            "playUrl": "",
            "url": "novel://" + json.dumps(data, ensure_ascii=False),
            "header": "",
        }

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def destroy(self):
        try:
            if self.session:
                self.session.close()
        except Exception:
            pass

    def localProxy(self, param):
        return None
