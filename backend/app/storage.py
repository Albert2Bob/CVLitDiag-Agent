"""SQLite 是事件的唯一真实来源。采用单进程本地工作进程部署。"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .security import PermissionDenied

TERMINAL = ("completed", "failed", "cancelled")


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(prefix):
    return f"{prefix}_{uuid4().hex}"


class Conflict(Exception):
    pass


class Store:
    def __init__(self, path, user_id="demo_researcher"):
        self.user_id = user_id
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA foreign_keys=ON;
            PRAGMA journal_mode=WAL;
            PRAGMA busy_timeout=5000;
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                description TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS threads (
                thread_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects,
                user_id TEXT NOT NULL, title TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES threads,
                project_id TEXT NOT NULL REFERENCES projects, question TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed','cancelled')),
                answer TEXT, error TEXT, created_at TEXT NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_run ON runs(thread_id)
                WHERE status IN ('queued','running');
            CREATE TABLE IF NOT EXISTS messages (
                ordinal INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT UNIQUE NOT NULL,
                thread_id TEXT NOT NULL REFERENCES threads, project_id TEXT NOT NULL,
                run_id TEXT NOT NULL REFERENCES runs, role TEXT NOT NULL,
                content TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                run_id TEXT NOT NULL REFERENCES runs, sequence INTEGER NOT NULL,
                event_id TEXT UNIQUE NOT NULL, timestamp TEXT NOT NULL,
                type TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(run_id,sequence));
            CREATE TABLE IF NOT EXISTS project_owners (
                project_id TEXT PRIMARY KEY REFERENCES projects, user_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects,
                metadata TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audits (
                ordinal INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES runs, kind TEXT NOT NULL, record TEXT NOT NULL);
        """)
        # 阶段 2 的无归属项目只在首次迁移时归给原固定开发身份。
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO project_owners SELECT project_id,'demo_researcher' FROM projects"
            )
            # 先检查列是否存在，让旧数据库重复启动时也能安全完成迁移。
            if "final_answer" not in {r["name"] for r in self.db.execute("PRAGMA table_info(runs)")}:
                self.db.execute("ALTER TABLE runs ADD COLUMN final_answer TEXT")
            self.db.execute("PRAGMA user_version=3")
        if not self.list_projects():
            self.create_project("科研空间", "阶段 3 · 结构化回答与只读工具；文档为模拟元数据")
        for p in self.list_projects():
            self.seed_documents(p["project_id"])

    def rows(self, sql, args=()):
        return [dict(row) for row in self.db.execute(sql, args).fetchall()]

    def list_projects(self):
        return self.rows(
            "SELECT p.* FROM projects p JOIN project_owners o USING(project_id) WHERE o.user_id=? ORDER BY created_at",
            (self.user_id,),
        )

    def check_project(self, project_id, user_id=None):
        if not self.rows(
            "SELECT 1 FROM project_owners WHERE project_id=? AND user_id=?",
            (project_id, user_id or self.user_id),
        ):
            raise PermissionDenied

    def seed_documents(self, project_id):
        from .schemas import DocumentMetadata

        # 阶段 3 使用显式开发夹具验证工具链，后续可直接替换为真实解析结果。
        doc = DocumentMetadata(
            document_id=project_id + "_demo",
            project_id=project_id,
            filename="开发模拟资料.md",
            file_type="md",
            created_at=now(),
        )
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO documents VALUES (?,?,?)",
                (doc.document_id, project_id, doc.model_dump_json()),
            )

    def documents(self, project_id, file_type=None, parse_status=None):
        self.check_project(project_id)
        docs = [
            json.loads(r["metadata"])
            for r in self.rows("SELECT metadata FROM documents WHERE project_id=?", (project_id,))
        ]
        return [
            d
            for d in docs
            if (not file_type or d["file_type"] == file_type)
            and (not parse_status or d["parse_status"] == parse_status)
        ]

    def document(self, document_id):
        rows = self.rows("SELECT * FROM documents WHERE document_id=?", (document_id,))
        if not rows:
            # 不区分“文档不存在”和“无权访问”，避免借错误信息枚举其他项目资源。
            raise PermissionDenied
        self.check_project(rows[0]["project_id"])
        return json.loads(rows[0]["metadata"])

    def save_audit(self, run_id, kind, record):
        with self.db:
            self.db.execute(
                "INSERT INTO audits(run_id,kind,record) VALUES (?,?,?)",
                (run_id, kind, json.dumps(record, ensure_ascii=False)),
            )

    def create_project(self, name, description=""):
        p = dict(project_id=identifier("project"), name=name, description=description, created_at=now())
        with self.db:
            self.db.execute("INSERT INTO projects VALUES (?,?,?,?)", tuple(p.values()))
            self.db.execute("INSERT INTO project_owners VALUES (?,?)", (p["project_id"], self.user_id))
        self.seed_documents(p["project_id"])
        return p

    def list_threads(self, project_id):
        self.check_project(project_id)
        return self.rows("SELECT * FROM threads WHERE project_id=? ORDER BY created_at", (project_id,))

    def thread(self, thread_id):
        rows = self.rows("SELECT * FROM threads WHERE thread_id=?", (thread_id,))
        if not rows:
            raise KeyError(thread_id)
        self.check_project(rows[0]["project_id"])
        if rows[0]["user_id"] != self.user_id:
            raise PermissionDenied
        return rows[0]

    def create_thread(self, project_id):
        self.check_project(project_id)
        if not self.rows("SELECT 1 FROM projects WHERE project_id=?", (project_id,)):
            raise KeyError(project_id)
        t = dict(
            thread_id=identifier("thread"),
            project_id=project_id,
            user_id=self.user_id,
            title="新会话",
            created_at=now(),
        )
        with self.db:
            self.db.execute("INSERT INTO threads VALUES (?,?,?,?,?)", tuple(t.values()))
        return t

    def messages(self, thread_id):
        self.thread(thread_id)
        return self.rows("SELECT * FROM messages WHERE thread_id=? ORDER BY ordinal", (thread_id,))

    def create_run(self, thread_id, project_id, question):
        if self.thread(thread_id)["project_id"] != project_id:
            raise KeyError(project_id)
        run_id = identifier("run")
        try:
            with self.db:
                self.db.execute(
                    "INSERT INTO runs(run_id,thread_id,project_id,question,status,answer,error,created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (run_id, thread_id, project_id, question, "queued", None, None, now()),
                )
                for role, content in [("user", question), ("assistant", "")]:
                    self.db.execute(
                        "INSERT INTO messages(message_id,thread_id,project_id,run_id,role,content,created_at) VALUES (?,?,?,?,?,?,?)",
                        (identifier("message"), thread_id, project_id, run_id, role, content, now()),
                    )
                self.db.execute(
                    "UPDATE threads SET title=? WHERE thread_id=? AND title='新会话'",
                    (question[:40], thread_id),
                )
        except sqlite3.IntegrityError as exc:
            raise Conflict("当前会话已有运行中的任务，请等待完成或先停止。") from exc
        return self.run(run_id)

    def run(self, run_id):
        rows = self.rows("SELECT * FROM runs WHERE run_id=?", (run_id,))
        if not rows:
            raise KeyError(run_id)
        self.thread(rows[0]["thread_id"])
        row = rows[0]
        structured = row.pop("final_answer")
        # 新记录优先返回完整契约；旧记录仍可从 answer 字段平滑读取。
        return {
            **row,
            "answer": json.loads(structured) if structured else row["answer"],
            "events": self.events(run_id),
            "evidence": [],
        }

    def events(self, run_id, after=0):
        rows = self.rows(
            "SELECT * FROM events WHERE run_id=? AND sequence>? ORDER BY sequence", (run_id, after)
        )
        return [{**r, "payload": json.loads(r["payload"])} for r in rows]

    def cursor(self, run_id, event_id):
        if not event_id:
            return 0
        rows = self.rows("SELECT sequence FROM events WHERE run_id=? AND event_id=?", (run_id, event_id))
        if not rows:
            raise ValueError("事件游标不存在或不属于当前任务。")
        return rows[0]["sequence"]

    def append(self, run_id, event_type, payload):
        # 以原子方式提交状态转换、终止回答/消息和事件。
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            if row["status"] in TERMINAL:
                return None
            if event_type == "run_started":
                if row["status"] != "queued":
                    return None
                self.db.execute("UPDATE runs SET status='running' WHERE run_id=?", (run_id,))
            if event_type in TERMINAL:
                answer = payload.get("answer") if event_type == "completed" else None
                structured = None
                if isinstance(answer, dict):
                    from .output_validation import validate_answer

                    # 兼容旧客户端的摘要字段，同时单独保存可恢复的结构化答案。
                    validated = validate_answer(answer, set())
                    structured = validated.model_dump_json()
                    answer = validated.summary
                error = payload.get("message")
                self.db.execute(
                    "UPDATE runs SET status=?,answer=?,error=? WHERE run_id=?",
                    (event_type, answer, error, run_id),
                )
                if structured:
                    self.db.execute("UPDATE runs SET final_answer=? WHERE run_id=?", (structured, run_id))
                if answer is not None:
                    self.db.execute(
                        "UPDATE messages SET content=? WHERE run_id=? AND role='assistant'", (answer, run_id)
                    )
            seq = self.db.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM events WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            e = dict(
                event_id=f"{run_id}:{seq}",
                run_id=run_id,
                sequence=seq,
                timestamp=now(),
                type=event_type,
                payload=payload,
            )
            self.db.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?)",
                (
                    run_id,
                    seq,
                    e["event_id"],
                    e["timestamp"],
                    event_type,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
        return e

    def recover_interrupted(self):
        for r in self.rows("SELECT run_id FROM runs WHERE status IN ('queued','running')"):
            self.append(
                r["run_id"],
                "failed",
                dict(
                    status="failed",
                    code="SERVICE_RESTARTED",
                    message="服务已重启，原任务无法继续，请重新生成。",
                ),
            )

    def history(self, run_id):
        r = self.run(run_id)
        rows = self.rows(
            """SELECT m.role,m.content FROM messages m JOIN runs r ON r.run_id=m.run_id
            WHERE m.thread_id=? AND (r.status='completed' OR r.run_id=?)
            AND m.content<>'' ORDER BY m.ordinal""",
            (r["thread_id"], run_id),
        )
        return rows
