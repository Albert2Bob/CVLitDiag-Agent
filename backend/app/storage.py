"""SQLite 业务、事件、文档索引和运行证据的唯一事实来源。"""

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


class DuplicateDocument(Conflict):
    def __init__(self, document_id):
        super().__init__("项目中已存在内容相同的文档。")
        self.document_id = document_id


class Store:
    def __init__(self, path, user_id="demo_researcher"):
        self.user_id = user_id
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._migrate()
        if not self.list_projects():
            self.create_project("科研空间", "阶段 4 · 真实文档入库与多路召回")
        for project in self.list_projects():
            self.seed_documents(project["project_id"])

    def _migrate(self):
        self.db.executescript("""
            PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;
            CREATE TABLE IF NOT EXISTS projects (project_id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS threads (thread_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects, user_id TEXT NOT NULL, title TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES threads, project_id TEXT NOT NULL REFERENCES projects, question TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed','cancelled')), answer TEXT, error TEXT, created_at TEXT NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_run ON runs(thread_id) WHERE status IN ('queued','running');
            CREATE UNIQUE INDEX IF NOT EXISTS runs_project_identity ON runs(run_id,project_id);
            CREATE TABLE IF NOT EXISTS messages (ordinal INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT UNIQUE NOT NULL, thread_id TEXT NOT NULL REFERENCES threads, project_id TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES runs, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (run_id TEXT NOT NULL REFERENCES runs, sequence INTEGER NOT NULL, event_id TEXT UNIQUE NOT NULL, timestamp TEXT NOT NULL, type TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run_id,sequence));
            CREATE TABLE IF NOT EXISTS project_owners (project_id TEXT PRIMARY KEY REFERENCES projects, user_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audits (ordinal INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs, kind TEXT NOT NULL, record TEXT NOT NULL);
        """)
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO project_owners SELECT project_id,'demo_researcher' FROM projects")
            if "final_answer" not in {r["name"] for r in self.db.execute("PRAGMA table_info(runs)")}:
                self.db.execute("ALTER TABLE runs ADD COLUMN final_answer TEXT")
            columns = {r["name"] for r in self.db.execute("PRAGMA table_info(documents)")}
            if columns and "filename" not in columns:
                self.db.execute("ALTER TABLE documents RENAME TO phase3_documents")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects,
                    filename TEXT NOT NULL, file_type TEXT NOT NULL, storage_key TEXT,
                    document_version INTEGER NOT NULL, content_hash TEXT NOT NULL, file_size INTEGER NOT NULL,
                    parse_status TEXT NOT NULL, parse_quality TEXT, page_count INTEGER,
                    access_scope TEXT NOT NULL, error_code TEXT, error_message TEXT,
                    extractor_name TEXT, extractor_version TEXT, source TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(project_id,content_hash,source),
                    UNIQUE(document_id,document_version),
                    UNIQUE(document_id,document_version,project_id));
                CREATE TABLE IF NOT EXISTS document_chunks (
                    chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL,
                    document_version INTEGER NOT NULL, project_id TEXT NOT NULL, title TEXT NOT NULL,
                    section TEXT NOT NULL, page_number INTEGER, page_end INTEGER, locator TEXT,
                    chunk_index INTEGER NOT NULL, content TEXT NOT NULL, content_hash TEXT NOT NULL,
                    access_scope TEXT NOT NULL, token_count INTEGER NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(document_id,document_version,chunk_index),
                    UNIQUE(chunk_id,document_id,document_version,project_id,access_scope),
                    FOREIGN KEY(document_id,document_version,project_id)
                        REFERENCES documents(document_id,document_version,project_id) ON DELETE CASCADE);
                CREATE INDEX IF NOT EXISTS chunks_scope ON document_chunks(project_id,document_id,document_version,access_scope);
                CREATE TABLE IF NOT EXISTS document_summaries (
                    document_id TEXT NOT NULL,
                    document_version INTEGER NOT NULL, project_id TEXT NOT NULL, summary TEXT NOT NULL,
                    content_hash TEXT NOT NULL, access_scope TEXT NOT NULL,
                    PRIMARY KEY(document_id,document_version),
                    FOREIGN KEY(document_id,document_version,project_id)
                        REFERENCES documents(document_id,document_version,project_id) ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS document_vectors (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL, document_version INTEGER NOT NULL, project_id TEXT NOT NULL,
                    access_scope TEXT NOT NULL, embedding_model TEXT NOT NULL,
                    embedding_version TEXT NOT NULL, embedding TEXT NOT NULL,
                    FOREIGN KEY(chunk_id,document_id,document_version,project_id,access_scope)
                        REFERENCES document_chunks(chunk_id,document_id,document_version,project_id,access_scope)
                        ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS run_evidence (
                    evidence_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                    project_id TEXT NOT NULL, document_id TEXT NOT NULL, document_version INTEGER NOT NULL,
                    chunk_id TEXT NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(run_id,chunk_id,document_version),
                    FOREIGN KEY(run_id,project_id) REFERENCES runs(run_id,project_id) ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS index_versions (
                    document_id TEXT NOT NULL,
                    document_version INTEGER NOT NULL, embedding_model TEXT NOT NULL,
                    embedding_version TEXT NOT NULL, chunking_version TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(document_id,document_version),
                    FOREIGN KEY(document_id,document_version)
                        REFERENCES documents(document_id,document_version) ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS document_events (
                    document_id TEXT NOT NULL REFERENCES documents ON DELETE CASCADE,
                    sequence INTEGER NOT NULL, timestamp TEXT NOT NULL, type TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(document_id,sequence));
                CREATE UNIQUE INDEX IF NOT EXISTS documents_version_identity
                    ON documents(document_id,document_version);
                CREATE UNIQUE INDEX IF NOT EXISTS documents_project_version_identity
                    ON documents(document_id,document_version,project_id);
                CREATE UNIQUE INDEX IF NOT EXISTS chunks_project_version_identity
                    ON document_chunks(chunk_id,document_id,document_version,project_id,access_scope);
            """)
            if self._table_exists("phase3_documents"):
                for row in self.rows("SELECT * FROM phase3_documents"):
                    try:
                        meta = json.loads(row["metadata"])
                    except (TypeError, ValueError):
                        continue
                    values = (
                        meta["document_id"], row["project_id"], meta.get("filename", "开发模拟资料.md"),
                        meta.get("file_type", "md"), None, 1, "fixture:" + meta["document_id"], 0,
                        "unsupported", None, meta.get("page_count"), "project", "DEVELOPMENT_FIXTURE",
                        "阶段 3 开发夹具不包含真实正文。", None, None, "development_fixture",
                        meta.get("created_at", now()), now(),
                    )
                    self.db.execute("INSERT OR IGNORE INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
            self.db.execute("PRAGMA user_version=4")

    def _table_exists(self, name):
        return bool(self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())

    def rows(self, sql, args=()):
        return [dict(row) for row in self.db.execute(sql, args).fetchall()]

    def list_projects(self):
        return self.rows("SELECT p.* FROM projects p JOIN project_owners o USING(project_id) WHERE o.user_id=? ORDER BY created_at", (self.user_id,))

    def check_project(self, project_id, user_id=None):
        if not self.rows("SELECT 1 FROM project_owners WHERE project_id=? AND user_id=?", (project_id, user_id or self.user_id)):
            raise PermissionDenied

    def create_project(self, name, description=""):
        item = dict(project_id=identifier("project"), name=name, description=description, created_at=now())
        with self.db:
            self.db.execute("INSERT INTO projects VALUES (?,?,?,?)", tuple(item.values()))
            self.db.execute("INSERT INTO project_owners VALUES (?,?)", (item["project_id"], self.user_id))
        self.seed_documents(item["project_id"])
        return item

    def seed_documents(self, project_id):
        """保留阶段 3 夹具的 ID 契约，但明确标记为不可检索的旧数据。"""
        document_id = project_id + "_demo"
        values = (
            document_id,
            project_id,
            "开发模拟资料.md",
            "md",
            None,
            1,
            "fixture:" + document_id,
            0,
            "unsupported",
            None,
            None,
            "project",
            "DEVELOPMENT_FIXTURE",
            "阶段 3 开发夹具不包含真实正文。",
            None,
            None,
            "development_fixture",
            now(),
            now(),
        )
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                values,
            )

    def documents(self, project_id, file_type=None, parse_status=None):
        self.check_project(project_id)
        query, args = "SELECT * FROM documents WHERE project_id=?", [project_id]
        if file_type:
            query += " AND file_type=?"
            args.append(file_type)
        if parse_status:
            query += " AND parse_status=?"
            args.append(parse_status)
        return [self._public_document(row) for row in self.rows(query + " ORDER BY created_at", args)]

    @staticmethod
    def _public_document(row):
        keys = ("document_id", "project_id", "filename", "file_type", "document_version", "content_hash", "file_size", "parse_status", "parse_quality", "page_count", "access_scope", "error_code", "error_message", "source", "created_at", "updated_at")
        return {key: row.get(key) for key in keys}

    def document(self, document_id, *, internal=False):
        rows = self.rows("SELECT * FROM documents WHERE document_id=?", (document_id,))
        if not rows:
            raise PermissionDenied
        self.check_project(rows[0]["project_id"])
        return rows[0] if internal else self._public_document(rows[0])

    def create_document(self, project_id, filename, file_type, storage_key, content_hash, file_size):
        self.check_project(project_id)
        duplicate = self.rows("SELECT document_id FROM documents WHERE project_id=? AND content_hash=? AND source='upload'", (project_id, content_hash))
        if duplicate:
            raise DuplicateDocument(duplicate[0]["document_id"])
        item = dict(document_id=identifier("document"), project_id=project_id, filename=filename, file_type=file_type, storage_key=storage_key, document_version=1, content_hash=content_hash, file_size=file_size, parse_status="uploaded", parse_quality=None, page_count=None, access_scope="project", error_code=None, error_message=None, extractor_name=None, extractor_version=None, source="upload", created_at=now(), updated_at=now())
        with self.db:
            self.db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", tuple(item.values()))
        return self._public_document(item)

    def set_document_status(self, document_id, status):
        with self.db:
            self.db.execute("UPDATE documents SET parse_status=?,updated_at=? WHERE document_id=?", (status, now(), document_id))

    def append_document_event(self, document_id, event_type, payload):
        with self.db:
            sequence = self.db.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM document_events WHERE document_id=?",
                (document_id,),
            ).fetchone()[0]
            self.db.execute(
                "INSERT INTO document_events VALUES (?,?,?,?,?)",
                (document_id, sequence, now(), event_type, json.dumps(payload, ensure_ascii=False)),
            )

    def document_events(self, document_id):
        self.document(document_id)
        rows = self.rows(
            "SELECT * FROM document_events WHERE document_id=? ORDER BY sequence", (document_id,)
        )
        return [{**row, "payload": json.loads(row["payload"])} for row in rows]

    def fail_document(self, document_id, code, message, unsupported=False):
        with self.db:
            self.db.execute("DELETE FROM document_vectors WHERE document_id=?", (document_id,))
            self.db.execute("DELETE FROM document_summaries WHERE document_id=?", (document_id,))
            self.db.execute("DELETE FROM document_chunks WHERE document_id=?", (document_id,))
            status = "unsupported" if unsupported else "failed"
            self.db.execute("UPDATE documents SET parse_status=?,error_code=?,error_message=?,updated_at=? WHERE document_id=?", (status, code, message, now(), document_id))

    def commit_document(self, document_id, extraction, chunks, vectors, embedding_model, embedding_version, chunking_version):
        import hashlib

        from .rag.summary_index import build_summary

        summary = build_summary(chunks)
        with self.db:
            self.db.execute("DELETE FROM document_chunks WHERE document_id=?", (document_id,))
            for chunk in chunks:
                self.db.execute("INSERT INTO document_chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", tuple(chunk.model_dump().values()))
            for chunk, vector in zip(chunks, vectors, strict=True):
                values = (chunk.chunk_id, document_id, chunk.document_version, chunk.project_id, chunk.access_scope, embedding_model, embedding_version, json.dumps(vector))
                self.db.execute("INSERT INTO document_vectors VALUES (?,?,?,?,?,?,?,?)", values)
            digest = hashlib.sha256(summary.encode()).hexdigest()
            self.db.execute("INSERT OR REPLACE INTO document_summaries VALUES (?,?,?,?,?,?)", (document_id, chunks[0].document_version, chunks[0].project_id, summary, digest, chunks[0].access_scope))
            self.db.execute("INSERT OR REPLACE INTO index_versions VALUES (?,?,?,?,?,?)", (document_id, chunks[0].document_version, embedding_model, embedding_version, chunking_version, now()))
            self.db.execute("UPDATE documents SET parse_status='ready',parse_quality=?,page_count=?,extractor_name=?,extractor_version=?,error_code=NULL,error_message=NULL,updated_at=? WHERE document_id=?", (extraction.parse_quality, extraction.page_count, extraction.extractor_name, extraction.extractor_version, now(), document_id))

    def delete_document(self, document_id):
        row = self.document(document_id, internal=True)
        if row["source"] != "upload":
            raise Conflict("开发夹具不能通过文档接口删除。")
        with self.db:
            self.db.execute("DELETE FROM documents WHERE document_id=?", (document_id,))
        return row

    def searchable_chunks(self, project_id, document_ids=None, access_scope="project"):
        self.check_project(project_id)
        query = "SELECT c.* FROM document_chunks c JOIN documents d ON d.document_id=c.document_id AND d.document_version=c.document_version WHERE c.project_id=? AND c.access_scope=? AND d.parse_status='ready'"
        args = [project_id, access_scope]
        if document_ids:
            query += f" AND c.document_id IN ({','.join('?' for _ in document_ids)})"
            args.extend(document_ids)
        return self.rows(query + " ORDER BY c.document_id,c.chunk_index", args)

    def searchable_vectors(self, project_id, document_ids, access_scope, model, version):
        allowed = {row["chunk_id"] for row in self.searchable_chunks(project_id, document_ids, access_scope)}
        rows = self.rows("SELECT v.embedding,v.embedding_model,v.embedding_version,c.* FROM document_vectors v JOIN document_chunks c USING(chunk_id) WHERE v.project_id=? AND v.access_scope=? AND v.embedding_model=? AND v.embedding_version=?", (project_id, access_scope, model, version))
        return [row for row in rows if row["chunk_id"] in allowed]

    def searchable_summaries(self, project_id, document_ids, access_scope):
        allowed = {row["document_id"] for row in self.searchable_chunks(project_id, document_ids, access_scope)}
        rows = self.rows("SELECT * FROM document_summaries WHERE project_id=? AND access_scope=?", (project_id, access_scope))
        return [row for row in rows if row["document_id"] in allowed]

    def chunk_model(self, row):
        from .rag.schemas import DocumentChunk

        return DocumentChunk.model_validate({key: row[key] for key in DocumentChunk.model_fields})

    def adjacent_chunk(self, chunk, offset):
        args = (chunk.project_id, chunk.document_id, chunk.document_version, chunk.access_scope, chunk.chunk_index + offset)
        rows = self.rows("SELECT * FROM document_chunks WHERE project_id=? AND document_id=? AND document_version=? AND access_scope=? AND chunk_index=?", args)
        return self.chunk_model(rows[0]) if rows else None

    def save_run_evidence(self, run_id, evidence):
        with self.db:
            for item in evidence:
                values = (item.evidence_id, run_id, item.project_id, item.document_id, item.document_version, item.chunk_id, item.model_dump_json(), now())
                self.db.execute("INSERT OR REPLACE INTO run_evidence VALUES (?,?,?,?,?,?,?,?)", values)

    def run_evidence(self, run_id):
        return [json.loads(row["snapshot"]) for row in self.rows("SELECT snapshot FROM run_evidence WHERE run_id=? ORDER BY rowid", (run_id,))]

    def save_audit(self, run_id, kind, record):
        with self.db:
            self.db.execute("INSERT INTO audits(run_id,kind,record) VALUES (?,?,?)", (run_id, kind, json.dumps(record, ensure_ascii=False)))

    def retrieval_attempted(self, run_id):
        for row in self.rows("SELECT record FROM audits WHERE run_id=? AND kind='tool'", (run_id,)):
            try:
                if json.loads(row["record"]).get("tool_name") == "search_project_documents":
                    return True
            except (TypeError, ValueError):
                continue
        return False

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
        item = dict(thread_id=identifier("thread"), project_id=project_id, user_id=self.user_id, title="新会话", created_at=now())
        with self.db:
            self.db.execute("INSERT INTO threads VALUES (?,?,?,?,?)", tuple(item.values()))
        return item

    def messages(self, thread_id):
        self.thread(thread_id)
        return self.rows("SELECT * FROM messages WHERE thread_id=? ORDER BY ordinal", (thread_id,))

    def create_run(self, thread_id, project_id, question):
        if self.thread(thread_id)["project_id"] != project_id:
            raise KeyError(project_id)
        run_id = identifier("run")
        try:
            with self.db:
                self.db.execute("INSERT INTO runs(run_id,thread_id,project_id,question,status,answer,error,created_at) VALUES (?,?,?,?,?,?,?,?)", (run_id, thread_id, project_id, question, "queued", None, None, now()))
                for role, content in (("user", question), ("assistant", "")):
                    values = (identifier("message"), thread_id, project_id, run_id, role, content, now())
                    self.db.execute("INSERT INTO messages(message_id,thread_id,project_id,run_id,role,content,created_at) VALUES (?,?,?,?,?,?,?)", values)
                self.db.execute("UPDATE threads SET title=? WHERE thread_id=? AND title='新会话'", (question[:40], thread_id))
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
        return {**row, "answer": json.loads(structured) if structured else row["answer"], "events": self.events(run_id), "evidence": self.run_evidence(run_id)}

    def events(self, run_id, after=0):
        rows = self.rows("SELECT * FROM events WHERE run_id=? AND sequence>? ORDER BY sequence", (run_id, after))
        return [{**row, "payload": json.loads(row["payload"])} for row in rows]

    def cursor(self, run_id, event_id):
        if not event_id:
            return 0
        rows = self.rows("SELECT sequence FROM events WHERE run_id=? AND event_id=?", (run_id, event_id))
        if not rows:
            raise ValueError("事件游标不存在或不属于当前任务。")
        return rows[0]["sequence"]

    def append(self, run_id, event_type, payload):
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

                    allowed = {item["evidence_id"] for item in self.run_evidence(run_id)}
                    validated = validate_answer(answer, allowed)
                    structured, answer = validated.model_dump_json(), validated.summary
                self.db.execute("UPDATE runs SET status=?,answer=?,error=? WHERE run_id=?", (event_type, answer, payload.get("message"), run_id))
                if structured:
                    self.db.execute("UPDATE runs SET final_answer=? WHERE run_id=?", (structured, run_id))
                if answer is not None:
                    self.db.execute("UPDATE messages SET content=? WHERE run_id=? AND role='assistant'", (answer, run_id))
            sequence = self.db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM events WHERE run_id=?", (run_id,)).fetchone()[0]
            event = dict(event_id=f"{run_id}:{sequence}", run_id=run_id, sequence=sequence, timestamp=now(), type=event_type, payload=payload)
            values = (run_id, sequence, event["event_id"], event["timestamp"], event_type, json.dumps(payload, ensure_ascii=False))
            self.db.execute("INSERT INTO events VALUES (?,?,?,?,?,?)", values)
        return event

    def recover_interrupted(self):
        for row in self.rows("SELECT run_id FROM runs WHERE status IN ('queued','running')"):
            payload = {"status": "failed", "code": "SERVICE_RESTARTED", "message": "服务已重启，原任务无法继续，请重新生成。"}
            self.append(row["run_id"], "failed", payload)

    def history(self, run_id):
        run = self.run(run_id)
        sql = """SELECT m.role,m.content FROM messages m JOIN runs r ON r.run_id=m.run_id
            WHERE m.thread_id=? AND (r.status='completed' OR r.run_id=?) AND m.content<>'' ORDER BY m.ordinal"""
        return self.rows(sql, (run["thread_id"], run_id))
