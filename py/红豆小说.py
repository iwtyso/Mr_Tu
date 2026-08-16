# -*- coding: utf-8 -*-
# PickTV / PeekPro 小说源 - 红豆小说
# 站点：https://www.hdongnet.com
import re
import json
import urllib.parse

from base.spider import Spider
from bs4 import BeautifulSoup
import requests


class Spider(Spider):
    def getName(self):
        return "红豆小说"

    def init(self, extend=""):
        self.host = "https://www.hdongnet.com"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.host,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        self.classes = [
            ("xuanhuanqihuan", "玄幻奇幻"), ("WuXiaXianXia", "武侠仙侠"),
            ("NvPinYanQing", "女频言情"), ("XianDaiDuShi", "现代都市"),
            ("LiShiJunShi", "历史军事"), ("YouXiJingJi", "游戏竞技"),
            ("KeHuanLingYi", "科幻灵异"), ("MeiWenTongRen", "美文同人"),
            ("Other", "其他类型"),
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

    def _fetch(self, url, timeout=15):
        try:
            resp = self.session.get(url, timeout=timeout)
            resp.encoding = "utf-8"
            return resp.text
        except Exception as e:
            print(f"[红豆小说 Fetch Error] {url} -> {e}")
            return ""

    def _og(self, soup, name):
        node = soup.select_one('meta[property="og:%s"]' % name)
        return node.get("content", "").strip() if node else ""

    # ---------------- 首页 / 分类 ----------------
    def homeContent(self, filter=False):
        return {"class": [{"type_id": tid, "type_name": name} for tid, name in self.classes]}

    def _parse_list_item(self, li):
        a = li.select_one("div.book-mid-info .t a") or li.select_one("a[href*='/hdxs/'], a[href*='/xs/']")
        if not a:
            return None
        href = a.get("href", "")
        if "/hdxs/" not in href and "/xs/" not in href:
            return None
        img = li.select_one("div.book-img-box img")
        pic = img.get("src", "") if img else ""
        author_node = li.select_one("div.book-mid-info p.author .fl")
        author = author_node.get_text(strip=True) if author_node else ""
        remark_node = li.select_one("div.book-mid-info p.author span:last-child")
        remark = remark_node.get_text(strip=True) if remark_node else author
        return {
            "vod_id": href,
            "vod_name": a.get_text(strip=True) or a.get("title", ""),
            "vod_pic": self._fix_url(pic),
            "vod_remarks": remark,
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

        # 轮播推荐（带封面）
        for li in soup.select("ul.banner_img li"):
            a = li.select_one("a[href*='/hdxs/']")
            if not a:
                continue
            img = li.select_one("img")
            title_node = li.select_one("p.tit a")
            writer_node = li.select_one("p.writer")
            add({
                "vod_id": a.get("href", ""),
                "vod_name": (title_node.get_text(strip=True) if title_node else "") or (img.get("alt", "") if img else ""),
                "vod_pic": self._fix_url(img.get("src", "")) if img else "",
                "vod_remarks": writer_node.get_text(strip=True) if writer_node else "",
            })
        # 最近更新
        for li in soup.select("ul.update_b li"):
            add(self._parse_update_item(li))
        return {"list": videos[:40]}

    def _parse_update_item(self, li):
        a = li.select_one("a[href*='/xs/'], a[href*='/hdxs/']")
        if not a:
            return None
        title = a.get("title", "") or a.get_text(strip=True)
        author_node = li.select_one("p.tab_3 a") or li.select_one("p.tab_3")
        date_node = li.select_one("span.tab_5")
        remark = (author_node.get_text(strip=True) if author_node else "") + " " + (date_node.get_text(strip=True) if date_node else "")
        return {
            "vod_id": a.get("href", ""),
            "vod_name": title.strip(),
            "vod_pic": "",
            "vod_remarks": remark.strip(),
        }

    def categoryContent(self, tid, pg, filter=False, extend=""):
        try:
            pg = int(pg) if pg else 1
        except ValueError:
            pg = 1
        url = f"{self.host}/category/{tid}.html?orderby=id&orderway=desc&page={pg}"
        html = self._fetch(url)
        if not html:
            return {"list": []}
        soup = BeautifulSoup(html, "html.parser")
        videos = []
        for li in soup.select("ul li"):
            if not li.select_one("div.book-mid-info"):
                continue
            book = self._parse_list_item(li)
            if book:
                videos.append(book)
        has_next = bool(soup.select_one("a[href*='page=%d']" % (pg + 1)))
        pagecount = pg + 1 if has_next else pg
        return {
            "list": videos,
            "page": pg,
            "pagecount": pagecount,
            "limit": 20,
            "total": pagecount * 20,
        }

    # ---------------- 搜索 ----------------
    def searchContent(self, key, quick=False, pg="1"):
        if int(pg or 1) > 1:
            return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}
        url = f"{self.host}/search?q=" + urllib.parse.quote(key)
        html = self._fetch(url)
        if not html:
            return {"list": []}
        soup = BeautifulSoup(html, "html.parser")
        videos = []
        for li in soup.select("ul li"):
            if not li.select_one("div.book-mid-info"):
                continue
            book = self._parse_list_item(li)
            if book:
                videos.append(book)
        return {"list": videos, "page": 1, "pagecount": 1, "limit": 20, "total": len(videos)}

    # ---------------- 详情 ----------------
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
        # 别名页(/xs/xx.html)解析 canonical 得到真实书籍页
        canon = soup.select_one('link[rel="canonical"]')
        real = canon.get("href", "") if canon else ""
        if real and "/hdxs/" in real:
            real = self._fix_url(real)
            if real.rstrip("/") != url.rstrip("/"):
                html = self._fetch(real)
                if not html:
                    return {}
                soup = BeautifulSoup(html, "html.parser")
                url = real
        title = self._og(soup, "title")
        title = re.sub(r"[_-]红豆小说网$", "", title)
        author = self._og(soup, "novel:author") or ""
        pic = self._fix_url(self._og(soup, "image"))
        desc = self._og(soup, "description") or ""
        chapters = []
        mulu = soup.select_one("div.mulu")
        if mulu:
            for a in mulu.select("ul li a"):
                href = a.get("href", "")
                if "/hdxs/" not in href:
                    continue
                chapters.append((a.get_text(strip=True), self._fix_url(href)))
        vod_play_url = "#".join([f"{t}${u}" for t, u in chapters])
        vod_id = url.replace(self.host, "")
        return {
            "list": [{
                "vod_id": vod_id,
                "vod_name": title or "书籍",
                "vod_pic": pic,
                "vod_author": author,
                "type_name": "",
                "vod_content": desc,
                "vod_play_from": "红豆小说",
                "vod_play_url": vod_play_url,
            }]
        }

    # ---------------- 章节正文 ----------------
    def playerContent(self, flag, id, vipFlags=None):
        url = id if str(id).startswith("http") else self._fix_url(id)
        try:
            html = self._fetch(url)
            if not html:
                return self._novel_result("章节", "未获取到章节内容")
            soup = BeautifulSoup(html, "html.parser")
            h1 = soup.select_one("h1")
            title = h1.get_text(strip=True) if h1 else "章节"
            art = soup.select_one("div.art_cnt")
            content = ""
            if art:
                # 去掉公众号插入广告块
                art_html = re.sub(r"<!--insert-->.*?<!--End insert-->", "", str(art), flags=re.S)
                art_soup = BeautifulSoup(art_html, "html.parser")
                paras = []
                for p in art_soup.select("p"):
                    t = p.get_text("\n", strip=True)
                    if not t:
                        continue
                    if any(k in t for k in ("继续阅读请关注公众号", "文元读物", "书号", "请关注公众号")):
                        continue
                    paras.append(t)
                content = "\n\n".join(paras)
            content = re.sub(r"\n\s*\n+", "\n\n", content).strip()
            if not content:
                content = "未获取到章节内容（该章节可能需跳转外部平台）"
            return self._novel_result(title, content)
        except Exception as e:
            print(f"[红豆小说 playerContent] {e}")
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
