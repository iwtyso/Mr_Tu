# -*- coding: utf-8 -*-
# PickTV / PeekPro 小说源 - 小说聚合搜索
# 在搜索框输入书名，一次并发搜索全部子源并合并结果。
# 结果 vod_id 带「源key::」前缀，详情/正文会自动路由回对应源。
import os
import sys
import json
import threading
import importlib.util
from concurrent.futures import ThreadPoolExecutor

from base.spider import Spider

# 参与聚合的子源（文件名 -> 路由 key），按推荐顺序排列
SUB_SOURCES = [
    ("燃文小说.py", "燃文小说"),
    ("笔趣阁.py", "笔趣阁"),
    ("灯笔小说.py", "灯笔小说"),
    ("顶点小说.py", "顶点小说"),
    ("七猫小说.py", "七猫小说"),
]

# 章节 URL 特征 -> 路由 key（用于 playerContent）
_URL_ROUTES = [
    ("qimao://", "七猫小说"),
    ("wxsy.net", "顶点小说"),
    ("dengbi.net", "灯笔小说"),
    ("ranwen.la", "燃文小说"),
    ("biquwu.cc", "笔趣阁"),
    ("fsshu.com", "笔趣阁"),
]


class Spider(Spider):
    def getName(self):
        return "小说聚合搜索"

    def getDependence(self):
        # 关键：告诉 app 需要一起下载的子源文件名（不带 .py，Java 侧会补 .py）
        # 否则 app 缓存里没有这些文件，聚合源会加载 0 个子源，首页/搜索全空。
        return [fname[:-3] for fname, _ in SUB_SOURCES]

    def init(self, extend=""):
        self.sources = {}  # key -> 子源实例
        self._lock = threading.Lock()
        here = self._module_dir()
        for fname, key in SUB_SOURCES:
            sp = self._load_source(here, fname, key)
            if sp is not None:
                self.sources[key] = sp
        print(f"[聚合搜索] 已加载 {len(self.sources)}/{len(SUB_SOURCES)} 个子源: {list(self.sources.keys())}")

    # ---------------- 加载子源 ----------------
    def _module_dir(self):
        try:
            return os.path.dirname(os.path.abspath(__file__))
        except Exception:
            pass
        # 兜底：从 sys.path 找 py 目录
        for p in sys.path:
            if p and os.path.isdir(p) and os.path.exists(os.path.join(p, "燃文小说.py")):
                return p
        # 常见兜底：PickTV/FongMi 的 py 缓存目录
        for base in (os.getcwd(), r"py", os.path.join(os.getcwd(), "py")):
            if os.path.isfile(os.path.join(base, "燃文小说.py")):
                return os.path.abspath(base)
        return os.getcwd()

    def _load_source(self, here, fname, key):
        path = os.path.join(here, fname)
        try:
            if os.path.exists(path):
                spec = importlib.util.spec_from_file_location("agg_" + key, path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            else:
                mod = importlib.import_module(fname[:-3])
            sp = mod.Spider()
            sp.init()
            return sp
        except Exception as e:
            print(f"[聚合搜索] 加载 {fname} 失败: {e}")
            return None

    # ---------------- 首页 / 分类 ----------------
    def homeContent(self, filter=False):
        return {"class": [{"type_id": "all", "type_name": "综合"}]}

    def _tag(self, book, name):
        book["vod_id"] = f"{name}::{book.get('vod_id', '')}"
        book["vod_remarks"] = name
        return book

    def homeVideoContent(self):
        videos, seen = [], set()

        def collect(name, sp):
            try:
                r = sp.homeVideoContent() or {}
            except Exception:
                r = {}
            for b in (r.get("list") or []):
                with self._lock:
                    b = self._tag(b, name)
                    k = (b.get("vod_name", ""), b.get("vod_author", ""))
                    if k not in seen:
                        seen.add(k)
                        videos.append(b)

        self._run_parallel(collect)
        return {"list": videos[:60]}

    def categoryContent(self, tid, pg, filter=False, extend=""):
        if tid != "all":
            return {"list": []}
        return self.homeVideoContent()

    # ---------------- 聚合搜索 ----------------
    def searchContent(self, key, quick=False, pg="1"):
        try:
            if int(pg or 1) > 1:
                return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}
        except Exception:
            pass
        if not self.sources:
            return {"list": []}
        results, seen = [], set()

        def do(name, sp):
            try:
                r = sp.searchContent(key, quick, "1") or {}
            except Exception as e:
                print(f"[聚合搜索] {name} 搜索异常: {e}")
                r = {}
            for b in (r.get("list") or []):
                b = self._tag(b, name)
                k = (str(b.get("vod_name", "")).strip(), str(b.get("vod_author", "")).strip())
                with self._lock:
                    if k not in seen:
                        seen.add(k)
                        results.append(b)

        self._run_parallel(do)
        return {"list": results, "page": 1, "pagecount": 1, "limit": 20, "total": len(results)}

    def _run_parallel(self, fn, timeout=15):
        if not self.sources:
            return
        ex = ThreadPoolExecutor(max_workers=len(self.sources))
        try:
            futs = {ex.submit(fn, name, sp): name for name, sp in self.sources.items()}
            for fut in futs:
                try:
                    fut.result(timeout=timeout)
                except Exception:
                    pass
        finally:
            # 不等待仍在跑的超时任务，避免拖住整个源
            ex.shutdown(wait=False, cancel_futures=True)

    # ---------------- 路由 ----------------
    def _split(self, rid):
        rid = str(rid)
        if "::" in rid:
            name, _, orig = rid.partition("::")
            if name in self.sources:
                return name, orig
        return "", rid

    def _route(self, url):
        name, _ = self._split(url)
        if name:
            return name
        u = str(url)
        for pat, key in _URL_ROUTES:
            if pat in u:
                return key
        return ""

    # ---------------- 详情 / 正文 ----------------
    def detailContent(self, ids):
        ids = ids if isinstance(ids, list) else [ids]
        name, orig = self._split(ids[0])
        sp = self.sources.get(name)
        if not sp:
            return {}
        try:
            r = sp.detailContent([orig]) or {}
        except Exception as e:
            print(f"[聚合搜索] {name} 详情异常: {e}")
            return {}
        for b in (r.get("list") or []):
            self._tag(b, name)
        return r

    def playerContent(self, flag, id, vipFlags=None):
        sid = str(id)
        name = self._route(sid)
        sp = self.sources.get(name)
        if not sp:
            return self._novel_result("错误", f"未找到对应源：{sid[:50]}")
        try:
            return sp.playerContent(flag, sid, vipFlags)
        except Exception as e:
            print(f"[聚合搜索] {name} 正文异常: {e}")
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
        for sp in self.sources.values():
            try:
                sp.destroy()
            except Exception:
                pass

    def localProxy(self, param):
        return None
