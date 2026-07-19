import json
import sqlite3

conn = sqlite3.connect("progress.db")
conn.row_factory = sqlite3.Row

s = conn.execute(
    "SELECT detail_json FROM attempts WHERE id=46"
).fetchone()["detail_json"]

decoder = json.JSONDecoder()

obj, idx = decoder.raw_decode(s)

print("JSON ended at index:", idx)
print("Total length:", len(s))
print("Remaining data:")
print(repr(s[idx:]))