"""
Re-normalize `jobs.location` (và `companies.city`) đã có trong DB bằng
`normalize_location` mới — gộp mọi biến thể của cùng một thành phố về một tên
tỉnh/thành chuẩn, giúp danh sách thành phố sạch và filter theo thành phố chính xác.

Mặc định CHẠY THỬ (dry-run) chỉ in thay đổi. Thêm --apply để ghi vào DB.

    python renormalize_locations.py            # xem trước (không ghi)
    python renormalize_locations.py --apply     # ghi thay đổi

Kết nối DB qua DATABASE_URL hoặc các biến POSTGRES_* (giống import.py).
"""
import os
import sys
import argparse
import psycopg2

from location_normalization import normalize_location


def get_db_connection():
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return psycopg2.connect(db_url)
    host = os.getenv("POSTGRES_HOST") or os.getenv("PG_HOST") or "localhost"
    port = os.getenv("POSTGRES_PORT") or os.getenv("PG_PORT") or "5432"
    db = os.getenv("POSTGRES_DB") or os.getenv("PG_DB") or "postgres"
    user = os.getenv("POSTGRES_USER") or os.getenv("PG_USER") or "postgres"
    pwd = os.getenv("POSTGRES_PASSWORD") or os.getenv("PG_PASSWORD")
    return psycopg2.connect(
        f"host={host} port={port} dbname={db} user={user} password={pwd}"
    )


def renormalize_column(conn, table, id_col, col, apply_changes):
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {id_col}, {col} FROM {table} WHERE {col} IS NOT NULL AND {col} <> ''"
        )
        rows = cur.fetchall()

    changes = []  # (id, old, new)
    for row_id, old in rows:
        new = normalize_location(old)
        if new != old:
            changes.append((row_id, old, new))

    before = {r[1] for r in rows}
    after = {(normalize_location(r[1]) or r[1]) for r in rows}
    print(
        f"[{table}.{col}] {len(rows)} dòng | {len(before)} giá trị -> "
        f"{len(after)} giá trị | {len(changes)} dòng đổi"
    )
    for _id, old, new in changes[:15]:
        print(f"    {old!r:45} -> {new!r}")
    if len(changes) > 15:
        print(f"    ... và {len(changes) - 15} dòng khác")

    if apply_changes and changes:
        with conn.cursor() as cur:
            for row_id, _old, new in changes:
                cur.execute(
                    f"UPDATE {table} SET {col} = %s WHERE {id_col} = %s",
                    (new, row_id),
                )
        conn.commit()
        print(f"    -> Đã cập nhật {len(changes)} dòng trong {table}.{col}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply", action="store_true", help="Ghi thay đổi vào DB (mặc định chỉ chạy thử)"
    )
    args = parser.parse_args()

    conn = get_db_connection()
    try:
        renormalize_column(conn, "jobs", "job_id", "location", args.apply)
        renormalize_column(conn, "companies", "company_id", "city", args.apply)
    finally:
        conn.close()

    if not args.apply:
        print("\n(Chạy thử — chưa ghi gì. Thêm --apply để cập nhật.)")


if __name__ == "__main__":
    sys.exit(main())
