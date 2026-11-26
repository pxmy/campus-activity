"""页面 9：工具调用日志（管理员），可按用户、工具、是否成功筛选。"""
import streamlit as st

from services.auth import require_role
from services.db import get_conn

st.set_page_config(page_title="工具调用日志", layout="wide")
st.title("工具调用日志")
require_role("admin")

conn = get_conn()
users = [r[0] for r in conn.execute("SELECT DISTINCT username FROM tool_logs").fetchall()]
tools = [r[0] for r in conn.execute("SELECT DISTINCT tool FROM tool_logs").fetchall()]
conn.close()

c1, c2, c3 = st.columns(3)
u = c1.selectbox("用户", ["全部"] + users)
t = c2.selectbox("工具", ["全部"] + tools)
ok = c3.selectbox("是否成功", ["全部", "成功", "被拒绝/失败"])

sql = "SELECT ts,username,role,tool,args_json,ok,message,duration_ms FROM tool_logs WHERE 1=1"
args = []
if u != "全部":
    sql += " AND username=?"; args.append(u)
if t != "全部":
    sql += " AND tool=?"; args.append(t)
if ok == "成功":
    sql += " AND ok=1"
elif ok == "被拒绝/失败":
    sql += " AND ok=0"
sql += " ORDER BY ts DESC"

conn = get_conn()
rows = conn.execute(sql, args).fetchall()
conn.close()
st.write("共 %d 条记录（含被拒绝的调用）" % len(rows))
if rows:
    import pandas as pd
    df = pd.DataFrame([dict(r) for r in rows])
    df["ok"] = df["ok"].map({1: "成功", 0: "失败"})
    st.dataframe(df, use_container_width=True)
    csv = df.to_csv(index=False, encoding="utf-8-sig")
    st.download_button("导出日志 CSV", csv, "tool_logs.csv")
else:
    st.info("暂无日志记录。使用工具调用助手后会产生记录。")
