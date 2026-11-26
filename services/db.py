"""数据库连接：全项目通过 get_conn() 获取连接，统一开启外键约束。"""
import os
import sqlite3
from pathlib import Path


def get_conn():
    """返回一个开启了外键约束的 sqlite3 连接；路径来自环境变量 DB_PATH。

    外层调用者可用 with conn: 控制事务。注意 register 等规则函数需要
    isolation_level=None 以显式控制事务，此时应传入由本函数额外参数创建的连接。
    """
    db_path = Path(os.getenv("DB_PATH", "data/app.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_conn_manual():
    """手动事务模式的连接（isolation_level=None），供需要显式 BEGIN 的规则使用。"""
    db_path = Path(os.getenv("DB_PATH", "data/app.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
