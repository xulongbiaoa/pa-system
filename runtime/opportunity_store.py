"""机会与任务的文件存储（设计 v2.2 §22.4 迁移桥梁）。

边界（与设计一致，不冒充 PostgreSQL）：单进程独占写入——第二个
写者 acquire 必须失败；状态与任务放在同一个 JSON 存储单元里，
tmp 写完 flush+fsync 后 os.replace 原子替换；只支持研究/影子，
禁止真实订单执行。多 worker 与事务语义归 PostgreSQL 实现。
"""

import json
import os
from dataclasses import asdict

from runtime.opportunities import Condition, Opportunity


class StoreLocked(RuntimeError):
    pass


class FileOpportunityStore:
    def __init__(self, path):
        self.path = path
        self.lock_path = path + ".lock"
        self._locked = False
        self.data = {"opportunities": {}, "tasks": []}
        if os.path.exists(path):
            with open(path) as f:
                self.data = json.load(f)

    # ---- 独占写锁 ----
    def acquire(self):
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise StoreLocked(f"已有写者持有锁：{self.lock_path}")
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        self._locked = True
        return self

    def release(self):
        if self._locked and os.path.exists(self.lock_path):
            os.remove(self.lock_path)
        self._locked = False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.save()
        self.release()

    # ---- 机会 ----
    def get(self, opportunity_id):
        raw = self.data["opportunities"].get(opportunity_id)
        if raw is None:
            return None
        raw = dict(raw)
        raw["conditions"] = [Condition(**c) for c in raw.get("conditions") or []]
        return Opportunity(**raw)

    def upsert(self, opp):
        self.data["opportunities"][opp.opportunity_id] = asdict(opp)

    def all_ids(self):
        return list(self.data["opportunities"].keys())

    # ---- 任务（outbox 语义：请求键唯一，重复登记返回既有任务）----
    def add_task(self, task):
        for t in self.data["tasks"]:
            if t["request_key"] == task["request_key"]:
                return t, False
        self.data["tasks"].append(task)
        return task, True

    def pending_tasks(self, type_=None):
        return [t for t in self.data["tasks"]
                if t.get("status") == "pending"
                and (type_ is None or t.get("type") == type_)]

    def complete_task(self, request_key, outcome):
        for t in self.data["tasks"]:
            if t["request_key"] == request_key:
                t["status"] = "done"
                t["outcome"] = outcome
                return t
        return None

    # ---- 落盘（原子替换）----
    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
