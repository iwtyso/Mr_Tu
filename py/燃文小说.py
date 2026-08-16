# -*- coding: utf-8 -*-
# PickTV / PeekPro 小说源 - 燃文小说
# 站点：https://www.ranwen.la
import re
import json
import base64
import time
import urllib.parse

from base.spider import Spider
from bs4 import BeautifulSoup
import requests


class Spider(Spider):
    def getName(self):
        return "燃文小说"

    def init(self, extend=""):
        self.host = "https://ranwen.la"  # 用裸域名更稳；站点会在桌面/移动模板间轮换，解析器已兼容两种
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.host,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        # 不走系统代理：本地 Clash 等代理会导致直连站点超时
        if hasattr(self.session, "trust_env"):
            self.session.trust_env = False
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

    def _fetch(self, url, timeout=20, tries=3, data=None):
        for i in range(tries):
            try:
                if data is not None:
                    resp = self.session.post(url, data=data, timeout=timeout)
                else:
                    resp = self.session.get(url, timeout=timeout)
                if resp.status_code == 200:
                    resp.encoding = "utf-8"
                    return resp.text
            except Exception as e:
                print(f"[燃文小说 Fetch Error] {url} -> {e}")
            if i < tries - 1:
                time.sleep(1)
        return ""

    def _og(self, soup, name):
        node = soup.select_one('meta[property="og:%s"]' % name)
        return node.get("content", "").strip() if node else ""

    # ---------------- 首页 / 分类 ----------------
    def homeContent(self, filter=False):
        return {"class": [{"type_id": tid, "type_name": name} for tid, name in self.classes]}

    def _parse_row(self, li):
        # 兼容站点两种列表模板：
        # 1) 桌面版：ul.txt-list li -> span.s2 a[href*='/oorw/']
        # 2) 移动版：li（如 .ph_list li）直接包含 a[href*='/oorw/']，且页面无 <img>，封面按书号合成
        a = li.select_one("span.s2 a[href*='/oorw/']") or li.select_one("a[href*='/oorw/']")
        if not a:
            return None
        href = a.get("href", "")
        m = re.search(r"/oorw/(\d+)/", href)
        if not m:
            return None
        bid = m.group(1)
        title = a.get_text(strip=True)
        title = re.sub(r"^\[[^\]]*\]\s*", "", title)
        chap = li.select_one("span.s3 a")
        author = li.select_one("span.s4") or li.select_one("span.s5 a[href*='/author/']")
        if author is None:
            author = li.select_one("a[href*='/author/']")
        remark = ""
        if author:
            remark = author.get_text(strip=True)
        if chap:
            remark = (remark + " " + chap.get_text(strip=True)).strip()
        return {
            "vod_id": f"/oorw/{bid}/",
            "vod_name": title or ("书籍" + bid),
            # 移动版页面没有 <img>，但 /img/{id}.jpg 封面一直有效，统一按书号合成
            "vod_pic": f"{self.host}/img/{bid}.jpg",
            "vod_remarks": remark,
        }

    def _parse_rows(self, soup):
        videos, seen = [], set()
        lis = soup.select("ul.txt-list li")
        if not lis:
            # 移动版模板没有 ul.txt-list，取所有包含 /oorw/ 链接的 li
            lis = [li for li in soup.select("li") if li.select_one("a[href*='/oorw/']")]
        for li in lis:
            b = self._parse_row(li)
            if b and b["vod_id"] not in seen:
                seen.add(b["vod_id"])
                videos.append(b)
        return videos


    def homeVideoContent(self):
        html = self._fetch(self.host)
        if not html:
            return {"list": []}
        soup = BeautifulSoup(html, "html.parser")
        return {"list": self._parse_rows(soup)[:60]}

    def categoryContent(self, tid, pg, filter=False, extend=""):
        try:
            pg = int(pg) if pg else 1
        except ValueError:
            pg = 1
        url = f"{self.host}/fenlei/{tid}/{pg}.html"
        html = self._fetch(url)
        if not html:
            return {"list": []}
        soup = BeautifulSoup(html, "html.parser")
        videos = self._parse_rows(soup)
        # 分页总数：取 lastupdate 分页链接中的最大页号
        pages = []
        for a in soup.select("a[href*='/fenlei/lastupdate_']"):
            m = re.search(r"lastupdate_\d+_\d+_\d+_(\d+)\.html", a.get("href", ""))
            if m:
                pages.append(int(m.group(1)))
        pagecount = max(pages) if pages else 1
        return {"list": videos, "page": pg, "pagecount": pagecount, "limit": 20, "total": len(videos)}

    # ---------------- 搜索 ----------------
    def searchContent(self, key, quick=False, pg="1"):
        if int(pg or 1) > 1:
            return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}
        html = self._fetch(f"{self.host}/search.html", data={"s": key})
        if not html:
            return {"list": []}
        soup = BeautifulSoup(html, "html.parser")
        videos = self._parse_rows(soup)
        return {"list": videos, "page": 1, "pagecount": 1, "limit": 20, "total": len(videos)}

    # ---------------- 详情 / 目录 ----------------
    def _collect_toc_page(self, html, bid, chapters):
        soup = BeautifulSoup(html, "html.parser")
        for ul in soup.select("ul.section-list.ycxsid"):
            for li in ul.select("li"):
                a = li.select_one("a")
                if not a:
                    continue
                # onclick="read_tz(9876032);" 或 onclick="amvzmchq(9876032);"
                m = re.search(r"\w+\((\d+)\);", a.get("onclick", ""))
                href = a.get("href", "")
                cid = None
                if m:
                    cid = m.group(1)
                else:
                    m2 = re.search(r"/books/%s/(\d+)\.html" % bid, href)
                    if m2:
                        cid = m2.group(1)
                if not cid:
                    continue
                title = a.get_text(strip=True)
                if cid not in chapters:
                    chapters[cid] = (title, f"{self.host}/books/{bid}/{cid}.html")

    def detailContent(self, ids):
        ids = ids if isinstance(ids, list) else [ids]
        rid = str(ids[0])
        if not rid.startswith(("http", "/")):
            rid = "/" + rid.lstrip("/")
        url = self._fix_url(rid)
        html = self._fetch(url)
        if not html:
            return {}
        soup = BeautifulSoup(html, "html.parser")
        title = self._og(soup, "novel:book_name") or self._og(soup, "title")
        author = self._og(soup, "novel:author")
        pic = self._fix_url(self._og(soup, "image"))
        category = self._og(soup, "novel:category")
        status = self._og(soup, "novel:status")
        desc = self._og(soup, "description") or ""
        # 章节目录入口 /books/{bid}/ml1.html
        toc_url = ""
        for a in soup.select("a[href*='/books/']"):
            t = a.get_text(strip=True)
            if "目录" in t or "章节" in t:
                m = re.search(r"/books/(\d+)/ml\d+\.html", a.get("href", ""))
                if m:
                    toc_url = a.get("href", "")
                    bid = m.group(1)
                    break
        chapters = {}
        if toc_url:
            toc_url = self._fix_url(toc_url)
            bid = re.search(r"/books/(\d+)/", toc_url).group(1)
            current = toc_url
            for _ in range(60):
                thtml = self._fetch(current)
                if not thtml:
                    break
                before = len(chapters)
                self._collect_toc_page(thtml, bid, chapters)
                # 下一页
                nxt = ""
                for a in BeautifulSoup(thtml, "html.parser").select("a[href*='/ml']"):
                    if a.get_text(strip=True) == "下一页":
                        nxt = a.get("href", "")
                        break
                if not nxt or len(chapters) == before:
                    break
                current = self._fix_url(nxt)
        vod_play_url = "#".join([f"{t}${u}" for cid, (t, u) in chapters.items()])
        return {
            "list": [{
                "vod_id": url.replace(self.host, ""),
                "vod_name": title or ("书籍"),
                "vod_pic": pic,
                "vod_author": author,
                "type_name": category,
                "vod_content": f"作者：{author}  {category}  {status}\n\n{desc}",
                "vod_play_from": "燃文小说",
                "vod_play_url": vod_play_url,
            }]
        }

    # ---------------- 章节正文 ----------------
    _FILLER = re.compile(
        r"^(书香门第.*|附：.*|={3,}|【全本校对】.*|作者[:：]\s*\S+$|内容简介[:：].*|请勿开启浏览器阅读模式.*|相邻推荐:?.*)$"
    )

    def _decode_content(self, html):
        """正文可能是 base64 混淆（yfbl.bfjlke），也可能是明文 <p>。"""
        b64s = re.findall(r"[\w$]+\.\w+\(['\"]([A-Za-z0-9+/=]{40,})['\"]\)", html)
        if b64s:
            chunks = []
            for b in b64s:
                try:
                    chunks.append(base64.b64decode(b).decode("utf-8", "ignore"))
                except Exception:
                    continue
            raw = "".join(chunks)
            cs = BeautifulSoup(raw, "html.parser")
            paras = []
            for p in cs.select("p"):
                t = p.get_text(strip=True)
                if t and not self._FILLER.match(t):
                    paras.append(t)
            return "\n\n".join(paras)
        # 明文 <p> 版本
        soup = BeautifulSoup(html, "html.parser")
        wr = soup.select_one("div.word_read")
        paras = []
        if wr:
            for p in wr.select("p"):
                t = p.get_text(strip=True)
                if t and not self._FILLER.match(t):
                    paras.append(t)
        return "\n\n".join(paras)

    def playerContent(self, flag, id, vipFlags=None):
        url = id if str(id).startswith("http") else self._fix_url(id)
        try:
            m = re.search(r"/books/\d+/(\d+)\.html", url)
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
                    h3 = soup.select_one("div.word_read h3")
                    if h3:
                        title = re.sub(r"[（(]第\d+页[)）]\s*$", "", h3.get_text(strip=True))
                text = self._decode_content(html)
                if text:
                    parts.append(text)
                nxt = ""
                for a in soup.select("a"):
                    if a.get_text(strip=True) in ("下一页", "下一章"):
                        nxt = a.get("href", "")
                        break
                if not nxt:
                    break
                nm = re.search(r"/books/\d+/(\d+)(?:_\d+)?\.html", nxt)
                if not nm:
                    break
                if base_cid and nm.group(1) != base_cid:
                    break
                current = self._fix_url(nxt)
            content = re.sub(r"\n\s*\n+", "\n\n", "\n\n".join(parts)).strip()
            if not content:
                content = "未获取到章节内容"
            return self._novel_result(title or "章节", content)
        except Exception as e:
            print(f"[燃文小说 playerContent] {e}")
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