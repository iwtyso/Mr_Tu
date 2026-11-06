# -*- coding: utf-8 -*-
# PickTV / PeekPro 小说源 - 起点小说
# 数据来自起点移动端公开页面，仅提供公开免费章节；VIP 章节遵守付费墙。
import html
import json
import re
import time
import urllib.parse

from base.spider import Spider
import requests

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None


class Spider(Spider):
    def getName(self):
        return "起点小说"

    def init(self, extend=""):
        self.host = "https://m.qidian.com"
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": self.host + "/",
        })
        self.classes = [
            ("4", "都市"), ("21", "玄幻"), ("1", "奇幻"), ("2", "武侠"),
            ("22", "仙侠"), ("5", "历史"), ("9", "科幻"), ("10", "悬疑"),
            ("12", "轻小说"), ("7", "游戏"), ("6", "军事"), ("8", "体育"),
            ("15", "现实"),
        ]
        self._csrf = ""
        self._csrf_ready = False

    # ---------------- 工具 ----------------
    def _fetch(self, url, params=None, timeout=25, tries=3, extra_headers=None):
        for i in range(tries):
            try:
                resp = self.session.get(
                    url,
                    params=params,
                    timeout=timeout,
                    headers=extra_headers or {},
                )
                if resp.status_code == 200:
                    resp.encoding = "utf-8"
                    return resp.text
                print(f"[起点小说] HTTP {resp.status_code}: {url}")
            except Exception as e:
                print(f"[起点小说] 请求失败 {url} -> {e}")
            if i < tries - 1:
                time.sleep(0.8 * (i + 1))
        return ""

    def _page_data(self, text):
        marker = '{"pageContext":'
        pos = text.find(marker) if text else -1
        if pos < 0:
            return {}
        try:
            data, _ = json.JSONDecoder().raw_decode(text[pos:])
            return (((data.get("pageContext") or {}).get("pageProps") or {}).get("pageData") or {})
        except Exception as e:
            print(f"[起点小说] 页面数据解析失败: {e}")
            return {}

    def _book_id(self, value):
        text = str(value or "")
        m = re.search(r"/book/(\d+)", text) or re.search(r"(\d{4,})", text)
        return m.group(1) if m else ""

    def _chapter_id(self, value):
        text = str(value or "")
        m = re.search(r"/chapter/(\d+)/(\d+)", text)
        if m:
            return m.group(1), m.group(2)
        return "", ""

    def _cover(self, book_id):
        return f"https://bookcover.yuewen.com/qdbimg/349573/{book_id}/180"

    def _book(self, item):
        bid = self._book_id(item.get("bid") or item.get("bookId") or "")
        if not bid:
            return None
        name = str(item.get("bName") or item.get("bookName") or "").strip()
        author = str(item.get("bAuth") or item.get("authorName") or "").strip()
        category = str(item.get("cat") or item.get("subCateName") or item.get("chanName") or "").strip()
        state = str(item.get("state") or item.get("bookStatus") or item.get("actionStatus") or "").strip()
        words = str(item.get("cnt") or item.get("showWordsCnt") or "").strip()
        desc = str(item.get("desc") or "").strip()
        pic = str(item.get("imgUrl") or item.get("coverUrl") or "").strip()
        if pic.startswith("//"):
            pic = "https:" + pic
        elif pic and not pic.startswith(("http://", "https://")):
            pic = self.host + "/" + pic.lstrip("/")
        remarks = " · ".join(x for x in (author, state, words) if x)
        return {
            "vod_id": bid,
            "vod_name": name or ("书籍" + bid),
            "vod_pic": pic or self._cover(bid),
            "vod_author": author,
            "vod_remarks": remarks,
            "vod_content": desc,
            "type_name": category,
        }

    def _books(self, items):
        result, seen = [], set()
        for item in items or []:
            book = self._book(item)
            if book and book["vod_id"] not in seen:
                seen.add(book["vod_id"])
                result.append(book)
        return result

    def _ensure_csrf(self):
        if self._csrf:
            return self._csrf
        # 分类页会下发 _csrfToken Cookie，公开分类接口需要同时回传它。
        self._fetch(self.host + "/category/catid4/")
        self._csrf = self.session.cookies.get("_csrfToken") or ""
        self._csrf_ready = bool(self._csrf)
        return self._csrf

    def _category_api(self, cat_id, page, retry=True):
        token = self._ensure_csrf()
        if not token:
            return {}
        params = {
            "catId": str(cat_id),
            "pageNum": int(page),
            "_csrfToken": token,
        }
        headers = {
            "Accept": "application/json, text/plain, */*",
            "x-csrf-token": token,
            "Referer": f"{self.host}/category/catid{cat_id}/",
        }
        try:
            resp = self.session.get(
                self.host + "/webcommon/category/list",
                params=params,
                headers=headers,
                timeout=25,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    return data.get("data") or {}
                if data.get("code") == 1403 and retry:
                    self._csrf = ""
                    self._csrf_ready = False
                    return self._category_api(cat_id, page, retry=False)
        except Exception as e:
            print(f"[起点小说] 分类接口失败: {e}")
        return {}

    # ---------------- 首页 / 分类 ----------------
    def homeContent(self, filter=False):
        return {"class": [{"type_id": tid, "type_name": name} for tid, name in self.classes]}

    def homeVideoContent(self):
        data = self._page_data(self._fetch(self.host + "/"))
        items = []
        for key in (
            "hotRank", "recRank", "signRank", "fyRank", "newSell", "bestSell",
            "popNovel", "limitFree", "xqRec", "wxRec", "dzRec", "ljRec",
            "yjRec", "klRec", "erRec",
        ):
            items.extend(data.get(key) or [])
        return {"list": self._books(items)}

    def categoryContent(self, tid, pg, filter=False, extend=""):
        page = int(pg or 1)
        data = self._category_api(tid, page)
        records = data.get("records") or []
        if not records:
            # 兜底：分类页首屏也内嵌了同样的数据。
            html_text = self._fetch(f"{self.host}/category/catid{tid}/")
            records = ((self._page_data(html_text).get("list") or {}).get("records") or [])
        result = {"list": self._books(records), "page": page}
        if data.get("isLast"):
            result["pagecount"] = page
        return result

    # ---------------- 搜索 ----------------
    def searchContent(self, key, quick=False, pg="1"):
        page = int(pg or 1)
        url = f"{self.host}/soushu/{urllib.parse.quote(str(key).strip(), safe='')}.html"
        params = {"pageNum": page} if page > 1 else None
        data = self._page_data(self._fetch(url, params=params))
        records = (data.get("bookInfo") or {}).get("records") or []
        return {"list": self._books(records)}

    # ---------------- 详情 / 目录 ----------------
    def detailContent(self, ids):
        ids = ids if isinstance(ids, list) else [ids]
        bid = self._book_id(str(ids[0]).split("::")[-1] if ids else "")
        if not bid:
            return {}
        info = self._page_data(self._fetch(f"{self.host}/book/{bid}/")).get("bookInfo") or {}
        catalog = self._page_data(self._fetch(f"{self.host}/book/{bid}/catalog/"))
        chapters = []
        for volume in catalog.get("vs") or []:
            for ch in volume.get("cs") or []:
                cid = str(ch.get("id") or "").strip()
                title = str(ch.get("cN") or "").strip()
                if cid and title:
                    chapters.append((cid, title))
        if not chapters:
            fallback = (self._page_data(self._fetch(f"{self.host}/book/{bid}/")).get("recentChapters") or [])
            for ch in reversed(fallback):
                cid = str(ch.get("id") or "").strip()
                title = str(ch.get("cN") or "").strip()
                if cid and title:
                    chapters.append((cid, title))

        def title_for_play(title):
            return title.replace("$", "＄").replace("#", "＃").replace("\n", " ").strip()

        play_urls = "#".join(
            f"{title_for_play(title)}${self.host}/chapter/{bid}/{cid}/"
            for cid, title in chapters
        )
        name = str(info.get("bookName") or "").strip() or ("书籍" + bid)
        author = str(info.get("authorName") or "").strip()
        category = str(info.get("subCateName") or info.get("chanName") or "").strip()
        status = str(info.get("bookStatus") or info.get("actionStatus") or "").strip()
        words = str(info.get("showWordsCnt") or "").strip()
        desc = str(info.get("desc") or "").strip()
        note = "起点官方公开源，仅公开免费章节可读；VIP 章节需在起点购买或订阅。"
        content = "\n".join(x for x in (
            f"作者：{author}" if author else "",
            f"分类：{category}" if category else "",
            f"状态：{status}" if status else "",
            f"字数：{words}" if words else "",
            note,
            desc,
        ) if x)
        return {
            "list": [{
                "vod_id": bid,
                "vod_name": name,
                "vod_pic": self._cover(bid),
                "vod_author": author,
                "type_name": category,
                "vod_remarks": " · ".join(x for x in (status, words) if x),
                "vod_content": content,
                "vod_play_from": "起点小说",
                "vod_play_url": play_urls,
            }]
        }

    # ---------------- 正文 ----------------
    def _clean_content(self, raw):
        if not raw:
            return ""
        if BeautifulSoup is not None:
            soup = BeautifulSoup(raw, "html.parser")
            for node in soup(["script", "style"]):
                node.decompose()
            text = soup.get_text("\n")
        else:
            text = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
            text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
            text = re.sub(r"<[^>]+>", "", text)
            text = html.unescape(text)
        lines = []
        for line in text.splitlines():
            line = re.sub(r"[ \t\u3000]+", " ", line).strip()
            if not line:
                continue
            if line in ("本章未完，请点击下一页继续阅读", "请勿开启浏览器阅读模式"):
                continue
            lines.append(line)
        return "\n\n".join(lines).strip()

    def playerContent(self, flag, id, vipFlags=None):
        bid, cid = self._chapter_id(id)
        if not bid or not cid:
            return self._novel_result("章节", "未获取到章节地址")
        data = self._page_data(self._fetch(f"{self.host}/chapter/{bid}/{cid}/"))
        info = data.get("chapterInfo") or {}
        title = str(info.get("chapterName") or "章节").strip()
        content = self._clean_content(info.get("content") or "")
        vip = str(info.get("vipStatus") or "0") == "1"
        bought = str(info.get("isBuy") or "0") == "1"
        if vip and not bought and len(content) < 800:
            message = "本章为起点 VIP 付费章节，公开页面仅提供试读片段。请在起点读书购买或订阅后阅读完整内容。"
            if content:
                message += "\n\n【公开试读】\n" + content
            return self._novel_result(title, message)
        if not content:
            return self._novel_result(title, "未获取到章节正文（可能需要登录、订阅或页面结构已变化）")
        return self._novel_result(title, content)

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
