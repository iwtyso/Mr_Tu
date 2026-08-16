# -*- coding: utf-8 -*-
# PickTV / PeekPro 小说源 - 灯笔小说
# 站点：https://www.dengbi.net
import re
import json
import time
import urllib.parse

from base.spider import Spider
from bs4 import BeautifulSoup
import requests


class Spider(Spider):
    def getName(self):
        return "灯笔小说"

    def init(self, extend=""):
        self.host = "https://www.dengbi.net"
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
            ("1", "玄幻"), ("2", "武侠"), ("3", "都市"),
            ("4", "历史"), ("5", "网游"), ("6", "科幻"),
            ("7", "言情"), ("8", "其他"),
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

    def _fetch(self, url, timeout=20, tries=3):
        for i in range(tries):
            try:
                resp = self.session.get(url, timeout=timeout)
                if resp.status_code == 200:
                    resp.encoding = "utf-8"
                    return resp.text
            except Exception as e:
                print(f"[灯笔小说 Fetch Error] {url} -> {e}")
            if i < tries - 1:
                time.sleep(1)
        return ""

    def _og(self, soup, name):
        node = soup.select_one('meta[property="og:%s"]' % name)
        return node.get("content", "").strip() if node else ""

    # ---------------- 首页 / 分类 ----------------
    def homeContent(self, filter=False):
        return {"class": [{"type_id": tid, "type_name": name} for tid, name in self.classes]}

    def _book_id(self, href):
        m = re.search(r"/(\d+)/(\d+)/", href or "")
        return f"{m.group(1)}/{m.group(2)}/" if m else ""

    def _parse_dl(self, dl):
        a = dl.select_one("h3 a") or dl.select_one("dt a")
        if not a:
            return None
        href = a.get("href", "")
        bid = self._book_id(href)
        if not bid:
            return None
        img = dl.select_one("dt img")
        pic = img.get("src", "") if img else ""
        title = a.get_text(strip=True) or a.get("title", "")
        title = re.sub(r"^\[[^\]]*\]\s*", "", title)
        author_node = dl.select_one(".book_other")
        author = author_node.get_text(" ", strip=True) if author_node else ""
        author = re.sub(r"^作者[:：]\s*", "", author)
        status_node = dl.select_one(".book_other + .book_other")
        status = status_node.get_text(strip=True) if status_node else ""
        return {
            "vod_id": bid,
            "vod_name": title or ("书籍" + bid),
            "vod_pic": self._fix_url(pic),
            "vod_remarks": f"{author} {status}".strip(),
        }

    def homeVideoContent(self):
        html = self._fetch(self.host)
        if not html:
            return {"list": []}
        soup = BeautifulSoup(html, "html.parser")
        videos, seen = [], set()

        def add(book):
            if book and book["vod_id"] not in seen:
                seen.add(book["vod_id"])
                videos.append(book)

        # 顶部推荐卡片（带封面）
        for card in soup.select("div.col-4.recommend"):
            a = card.select_one("div.pic a.img[href]")
            if not a:
                a = card.select_one("h3 a[href]") or card.select_one("a[href]")
            if not a:
                continue
            bid = self._book_id(a.get("href", ""))
            if not bid:
                continue
            img = card.select_one("div.pic img")
            pic = img.get("src", "") if img else ""
            h3 = card.select_one("h3 a")
            title = h3.get_text(strip=True) if h3 else (img.get("alt", "") if img else "")
            info = card.select_one("p.info")
            remark = info.get_text(" ", strip=True) if info else ""
            add({
                "vod_id": bid,
                "vod_name": title or ("书籍" + bid),
                "vod_pic": self._fix_url(pic),
                "vod_remarks": remark,
            })
        # 最新入库 / 最新更新 列表
        for row in soup.select("div.tab-content"):
            a = row.select_one("div.bookname a[href]")
            if not a:
                continue
            bid = self._book_id(a.get("href", ""))
            if not bid:
                continue
            chap = row.select_one("div.chap a")
            author = row.select_one("div.author")
            remark = ""
            if chap:
                remark = "更新：" + chap.get_text(strip=True)
            if author:
                remark = (author.get_text(strip=True) + " " + remark).strip()
            add({
                "vod_id": bid,
                "vod_name": a.get_text(strip=True) or ("书籍" + bid),
                "vod_pic": "",
                "vod_remarks": remark,
            })
        return {"list": videos[:60]}

    def categoryContent(self, tid, pg, filter=False, extend=""):
        try:
            pg = int(pg) if pg else 1
        except ValueError:
            pg = 1
        url = f"{self.host}/list{tid}/" if pg <= 1 else f"{self.host}/list{tid}/{pg}.html"
        html = self._fetch(url)
        if not html:
            return {"list": []}
        soup = BeautifulSoup(html, "html.parser")
        videos = [b for b in (self._parse_dl(dl) for dl in soup.select("dl")) if b]
        # 分页总数：取 pager 中 index 最大数字（» 指向末页）
        pages = [int(m.group(1)) for a in soup.select("a[href*='/list']") for m in [re.search(r"/list\d+/(\d+)\.html", a.get("href", ""))] if m]
        pagecount = max(pages) if pages else 1
        return {"list": videos, "page": pg, "pagecount": pagecount, "limit": 20, "total": len(videos)}

    # ---------------- 搜索 ----------------
    def searchContent(self, key, quick=False, pg="1"):
        try:
            pg = int(pg) if pg else 1
        except ValueError:
            pg = 1
        url = f"{self.host}/search.php?q={urllib.parse.quote(key)}&p={pg}"
        html = self._fetch(url)
        if not html:
            return {"list": []}
        soup = BeautifulSoup(html, "html.parser")
        videos = [b for b in (self._parse_dl(dl) for dl in soup.select("dl")) if b]
        pages = []
        for a in soup.select("a[href*='search.php']"):
            m = re.search(r"[?&]p=(\d+)", a.get("href", ""))
            if m:
                pages.append(int(m.group(1)))
        pagecount = max(pages) if pages else 1
        return {"list": videos, "page": pg, "pagecount": pagecount, "limit": 20, "total": len(videos)}

    # ---------------- 详情 / 目录 ----------------
    def _toc_pages(self, soup):
        pages = []
        for a in soup.select("a[href*='index_']"):
            m = re.search(r"index_(\d+)\.html", a.get("href", ""))
            if m:
                pages.append(int(m.group(1)))
        return max(pages) if pages else 1

    def _collect_toc(self, soup, chapters):
        for bl in soup.select("div.book_list"):
            # 跳过“最新12章节”块，避免与全章节列表重复
            prev = None
            for sib in (bl.parent.find_all(recursive=False) if bl.parent else []):
                if sib is bl:
                    break
                if sib.name in ("b", "h2", "h3", "h4"):
                    prev = sib
            if prev and "最新12章节" in prev.get_text():
                continue
            for a in bl.select("ul.row li a[href]"):
                href = a.get("href", "")
                if re.search(r"/\d+/\d+/\d+\.html", href) and href not in chapters:
                    chapters[href] = a.get_text(strip=True)

    def detailContent(self, ids):
        ids = ids if isinstance(ids, list) else [ids]
        rid = str(ids[0])
        if not rid.startswith(("http", "/")):
            rid = "/" + rid.lstrip("/")
        url = self._fix_url(rid)
        if not url.endswith("/"):
            url += "/"
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
        # 目录分页
        total = self._toc_pages(soup)
        chapters = {}
        for page in range(1, total + 1):
            toc_url = url if page <= 1 else url.rstrip("/") + f"/index_{page}.html"
            thtml = self._fetch(toc_url)
            if not thtml:
                continue
            self._collect_toc(BeautifulSoup(thtml, "html.parser"), chapters)
        vod_play_url = "#".join([f"{t}${self._fix_url(h)}" for h, t in chapters.items()])
        return {
            "list": [{
                "vod_id": url.replace(self.host, ""),
                "vod_name": title or ("书籍" + url.rstrip("/").split("/")[-1]),
                "vod_pic": pic,
                "vod_author": author,
                "type_name": category,
                "vod_content": f"作者：{author}  {category}  {status}\n\n{desc}",
                "vod_play_from": "灯笔小说",
                "vod_play_url": vod_play_url,
            }]
        }

    # ---------------- 章节正文 ----------------
    def playerContent(self, flag, id, vipFlags=None):
        url = id if str(id).startswith("http") else self._fix_url(id)
        try:
            m = re.search(r"/(\d+)\.html", url)
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
                    h1 = soup.select_one("h1")
                    if h1:
                        t = h1.get_text(strip=True)
                        title = re.sub(r"[-－]\s*《.*》\s*$", "", t)
                art = soup.select_one("article")
                if art:
                    for line in art.get_text("\n").split("\n"):
                        line = line.strip().replace("\u3000", " ").strip()
                        if not line:
                            continue
                        if re.match(r"^第\(\d+/\d+\)页$", line):
                            continue
                        parts.append(line)
                nxt = ""
                for a in soup.select("a"):
                    if a.get_text(strip=True) == "下一章":
                        nxt = a.get("href", "")
                        break
                if not nxt:
                    break
                nm = re.search(r"/(\d+)(?:_\d+)?\.html", nxt)
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
            print(f"[灯笔小说 playerContent] {e}")
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
