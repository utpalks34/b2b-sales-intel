from app.core.db import get_connection
from langgraph.checkpoint.postgres import PostgresSaver

conn = get_connection()
conn.autocommit = True
checkpointer = PostgresSaver(conn)
checkpointer.setup()
conn.close()
print("Checkpoint tables created.")
