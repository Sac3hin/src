
# backend/chunker.py
from typing import List
import pandas as pd

def csv_rows_to_chunks(csv_bytes: bytes, rows_per_chunk: int = 100) -> List[str]:
    """
    Convert CSV bytes into text chunks. Each chunk contains up to rows_per_chunk rows.
    """
    df = pd.read_csv(pd.io.common.BytesIO(csv_bytes))
    chunks: List[str] = []
    cols = list(df.columns)

    # Build row textual representation
    def row_to_text(row) -> str:
        parts = [f"{c}: {row[c]}" for c in cols]
        return "; ".join(parts)

    # Group rows into chunks
    buf: List[str] = []
    for _, row in df.iterrows():
        buf.append(row_to_text(row))
        if len(buf) >= rows_per_chunk:
            chunks.append("\n".join(buf))
            buf = []
    if buf:
        chunks.append("\n".join(buf))
    return chunks
