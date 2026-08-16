# -*- coding: utf-8 -*-
# PickTV / PeekPro 小说源 - 七猫小说
# 说明：七猫正文无轻量单章接口，采用"整本 zip 下载 + 磁盘缓存"方案。
#   首次阅读某本书时下载整本（约几 MB~十几 MB），缓存到系统临时目录，
#   之后各章节直接读缓存解密，速度快。
import re
import os
import json
import hashlib
import base64
import zipfile
import tempfile
import urllib.parse

from base.spider import Spider
import requests

try:
    from Crypto.Cipher import AES
except Exception:
    AES = None


class Spider(Spider):
    def getName(self):
        return "七猫小说"

    def init(self, extend=""):
        self.sign_key = "d3dGiJc651gSQ8w1"
        self.aes_key = bytes.fromhex("32343263636238323330643730396531")
        self.versions = [
            "73720", "73700", "73620", "73600", "73500", "73420", "73400",
            "73328", "73325", "73320", "73300", "73220", "73200", "73100",
            "73000", "72900", "72820", "72800", "70720", "62010", "62112",
        ]
        self.api_bc = "https://api-bc.wtzw.com"
        self.api_ks = "https://api-ks.wtzw.com"
        self.rank_api = "https://www.qimao.com/qimaoapi/api/rank/book-list"
        self.session = requests.Session()
        # 不走系统代理：本地代理会干扰直连
        self.session.trust_env = False
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        })
        self.classes = [
            ("0|1", "男生·大热榜"), ("0|2", "男生·新书榜"), ("0|3", "男生·完结榜"),
            ("1|1", "女生·大热榜"), ("1|2", "女生·新书榜"), ("1|3", "女生·完结榜"),
            ("0|4", "收藏榜"), ("0|6", "更新榜"),
        ]
        self._zip_dir = os.path.join(tempfile.gettempdir(), "qimao_cache")
        try:
            os.makedirs(self._zip_dir, exist_ok=True)
        except Exception:
            pass

    # ---------------- 签名 / 请求 ----------------
    def _md5(self, s):
        return hashlib.md5(s.encode("utf-8")).hexdigest()

    def _sign(self, params):
        return self._md5("".join(k + "=" + str(params[k]) for k in sorted(params)) + self.sign_key)

    def _stable_hash(self, s):
        h = 0
        for ch in s:
            h = (h * 31 + ord(ch)) & 0xFFFFFFFF
        if h >= 0x80000000:
            h -= 0x100000000
        return h

    def _headers(self, book_id):
        h = self._stable_hash(book_id) if book_id else 0
        idx = abs(h) % len(self.versions)
        hdrs = {
            "AUTHORIZATION": "",
            "app-version": self.versions[idx],
            "application-id": "com.****.reader",
            "channel": "unknown",
            "net-env": "1",
            "platform": "android",
            "qm-params": "",
            "reg": "0",
        }
        hdrs["sign"] = self._sign(hdrs)
        return hdrs

    def _api(self, base, path, params, book_id):
        params = dict(params)
        params["sign"] = self._sign(params)
        headers = self._headers(book_id)
        try:
            resp = self.session.get(base + path, params=params, headers=headers, timeout=25)
            return resp.json()
        except Exception as e:
            print(f"[七猫小说 api error] {path} -> {e}")
            return {}

    def _get(self, url, timeout=30, headers=None):
        try:
            return self.session.get(url, headers=headers or {}, timeout=timeout)
        except Exception as e:
            print(f"[七猫小说 get error] {url} -> {e}")
            return None

    # ---------------- 首页 / 分类 ----------------
    def homeContent(self, filter=False):
        return {"class": [{"type_id": tid, "type_name": name} for tid, name in self.classes]}

    def _rank_books(self, is_girl, rank_type, page=1):
        params = {
            "is_girl": is_girl,
            "rank_type": rank_type,
            "page": str(page),
            "date_type": "1" if rank_type in ("4", "6") else "2",
        }
        try:
            r = self.session.get(self.rank_api, params=params, timeout=25)
            data = r.json()
        except Exception as e:
            print(f"[七猫小说 rank error] {e}")
            return []
        out = []
        for it in (data.get("data") or {}).get("table_data") or []:
            bid = str(it.get("book_id") or "")
            if not bid:
                continue
            title = str(it.get("title") or "").strip()
            author = str(it.get("author") or "").strip()
            cat = " ".join(x for x in [
                str(it.get("category1_name") or ""),
                str(it.get("category2_name") or ""),
            ] if x)
            status = "完结" if str(it.get("is_over")) == "1" else "连载"
            hot = str(it.get("number") or "") + str(it.get("unit") or "")
            remarks = " ".join(x for x in [cat, status, hot] if x)
            out.append({
                "vod_id": bid,
                "vod_name": title or ("书籍" + bid),
                "vod_pic": str(it.get("image_link") or ""),
                "vod_remarks": remarks,
                "vod_content": str(it.get("intro") or ""),
                "vod_author": author,
            })
        return out

    def homeVideoContent(self):
        return {"list": self._rank_books("0", "1", 1)[:40]}

    def categoryContent(self, tid, pg, filter=False, extend=""):
        try:
            pg = int(pg) if pg else 1
        except ValueError:
            pg = 1
        m = re.match(r"^(\d)\|(\d+)$", str(tid))
        if not m:
            return {"list": []}
        books = self._rank_books(m.group(1), m.group(2), pg)
        pagecount = pg + 1 if books else pg
        return {
            "list": books,
            "page": pg,
            "pagecount": pagecount,
            "limit": len(books) or 20,
            "total": (len(books) or 20) * pagecount,
        }

    # ---------------- 搜索 ----------------
    def searchContent(self, key, quick=False, pg="1"):
        if int(pg or 1) > 1:
            return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}
        d = self._api(self.api_bc, "/search/v1/words", {
            "extend": "", "tab": "0", "gender": "0", "refresh_state": "8", "page": "1",
            "wd": key, "is_short_story_user": "0",
        }, "00000000")
        out = []
        for it in (d.get("data") or {}).get("books") or []:
            bid = str(it.get("id") or "")
            if not bid:
                continue
            title = re.sub(r"<[^>]+>", "", str(it.get("title") or "")).strip()
            author = re.sub(r"<[^>]+>", "", str(it.get("author") or "")).strip()
            sub = re.sub(r"<[^>]+>", "", str(it.get("sub_title") or "")).strip()
            out.append({
                "vod_id": bid,
                "vod_name": title or ("书籍" + bid),
                "vod_pic": str(it.get("image_link") or ""),
                "vod_remarks": " ".join(x for x in [author, sub] if x),
            })
        return {"list": out, "page": 1, "pagecount": 1, "limit": 20, "total": len(out)}

    # ---------------- 详情 ----------------
    def detailContent(self, ids):
        ids = ids if isinstance(ids, list) else [ids]
        m = re.search(r"(\d+)", str(ids[0]))
        if not m:
            return {}
        book_id = m.group(1)
        d = self._api(self.api_bc, "/api/v4/book/detail", {
            "id": book_id, "imei_ip": "2937357107", "teeny_mode": "0",
        }, book_id)
        book = (d.get("data") or {}).get("book") or {}
        title = str(book.get("title") or "书籍").strip()
        author = str(book.get("author") or "").strip()
        pic = str(book.get("image_link") or "")
        intro = str(book.get("intro") or "").strip()
        cat = " ".join(x for x in [
            str(book.get("category1_name") or ""),
            str(book.get("category2_name") or ""),
        ] if x)
        tags = []
        for t in (book.get("book_tag_list") or []):
            tname = str(t.get("title") or "").strip() if isinstance(t, dict) else ""
            if tname:
                tags.append(tname)
        chapters = self._chapters(book_id)
        if not chapters:
            return {}
        vod_play_url = "#".join([
            f"{t}$qimao://{book_id}/{cid}/{urllib.parse.quote(t)}" for cid, t in chapters
        ])
        desc = "\n\n".join(x for x in [
            ("作者：" + author + "  " + cat).strip(),
            intro,
            ("标签：" + "、".join(tags)) if tags else "",
        ] if x)
        return {
            "list": [{
                "vod_id": book_id,
                "vod_name": title,
                "vod_pic": pic,
                "vod_author": author,
                "type_name": cat,
                "vod_content": desc,
                "vod_play_from": "七猫小说",
                "vod_play_url": vod_play_url,
            }]
        }

    def _chapters(self, book_id):
        d = self._api(self.api_ks, "/api/v1/chapter/chapter-list", {
            "chapter_ver": "0", "id": book_id,
        }, book_id)
        raw = (d.get("data") or {}).get("chapter_lists") or []
        chs = []
        for it in raw:
            cid = str(it.get("id") or "")
            t = str(it.get("title") or "").strip()
            if cid and t:
                chs.append((cid, t))
        # 按章节 ID 升序
        try:
            chs.sort(key=lambda x: int(x[0]))
        except Exception:
            pass
        return chs

    # ---------------- 章节正文（整本 zip 缓存） ----------------
    def _zip_path(self, book_id):
        return os.path.join(self._zip_dir, "qimao_%s.zip" % book_id)

    def _download_zip(self, book_id):
        path = self._zip_path(book_id)
        if os.path.exists(path) and os.path.getsize(path) > 1024:
            return path
        d = self._api(self.api_bc, "/api/v1/book/download", {
            "id": book_id, "source": "1", "type": "2", "is_vip": "1",
        }, book_id)
        link = ((d.get("data") or {}).get("link") or "")
        if not link:
            print(f"[七猫小说] 未获取到下载链接 book={book_id}")
            return None
        resp = self._get(link, timeout=180, headers=self._headers(""))
        if resp is None or resp.status_code != 200 or not resp.content:
            print(f"[七猫小说] 整本下载失败 book={book_id}")
            return None
        tmp = path + ".tmp"
        try:
            with open(tmp, "wb") as f:
                f.write(resp.content)
            os.replace(tmp, path)
        except Exception as e:
            print(f"[七猫小说] 写入缓存失败 {e}")
        return path

    def _decrypt_chapter(self, data):
        try:
            text = data.decode("utf-8", "ignore")
        except Exception:
            text = ""
        if AES is None or not text.strip():
            return text
        try:
            raw = base64.b64decode(text)
            if len(raw) < 16:
                return text
            iv, ct = raw[:16], raw[16:]
            if len(ct) % 16 != 0:
                return text
            plain = AES.new(self.aes_key, AES.MODE_CBC, iv).decrypt(ct)
            pad = plain[-1]
            if 1 <= pad <= 16 and pad <= len(plain):
                plain = plain[:-pad]
            return plain.decode("utf-8", "ignore")
        except Exception as e:
            print(f"[七猫小说] 解密失败 {e}")
            return text

    def _read_chapter(self, book_id, chapter_id):
        path = self._download_zip(book_id)
        if not path:
            return None
        try:
            with zipfile.ZipFile(path) as z:
                target = None
                for n in z.namelist():
                    if n == chapter_id or n == chapter_id + ".txt" or n.rstrip(".txt") == chapter_id:
                        target = n
                        break
                if target is None:
                    return None
                data = z.read(target)
        except Exception as e:
            print(f"[七猫小说] 读取缓存失败 {e}")
            return None
        return self._decrypt_chapter(data)

    def playerContent(self, flag, id, vipFlags=None):
        sid = str(id)
        # 兼容两种格式：qimao://book/cid/标题 与 book:cid
        if "%" in sid:
            try:
                sid = urllib.parse.unquote(sid)
            except Exception:
                pass
        title = ""
        m = re.match(r"^qimao://(\d+)/(\d+)/(.*)$", sid)
        if m:
            book_id, chapter_id, title = m.group(1), m.group(2), m.group(3)
            if "%" in title:
                try:
                    title = urllib.parse.unquote(title)
                except Exception:
                    pass
        else:
            m2 = re.match(r"^(\d+):(\d+)$", sid)
            if m2:
                book_id, chapter_id = m2.group(1), m2.group(2)
            else:
                book_id, chapter_id = sid, ""
        if not chapter_id:
            return self._novel_result("章节", "未获取到章节内容")
        content = self._read_chapter(book_id, chapter_id)
        if not content:
            content = "未获取到章节内容（可能需会员或下载失败）"
        return self._novel_result(title or "章节", content)

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
