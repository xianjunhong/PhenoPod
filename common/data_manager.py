"""
Data manager for soybean-pod measurement records.

Records are stored in SQLite for fast append/delete/load operations. Existing
JSON data is imported once on first run and then kept as a backup.
"""
import csv
import json
import os
import sqlite3
from datetime import datetime


class DataManager:
    """Manage pod-measurement data, source images, and visualization images."""

    def __init__(self, config_manager):
        self.config_manager = config_manager
        paths = config_manager.get_paths_config()
        self.data_file = paths['data_file']
        self.images_folder = paths['images_folder']
        self.processed_folder = paths['processed_folder']

        base_path, _ = os.path.splitext(self.data_file)
        self.sqlite_file = base_path + '.db'

        self._ensure_folders()
        self._ensure_database()
        self._migrate_json_once()

    def _ensure_folders(self):
        for folder in [self.images_folder, self.processed_folder]:
            os.makedirs(folder, exist_ok=True)

        data_dir = os.path.dirname(self.sqlite_file)
        if data_dir:
            os.makedirs(data_dir, exist_ok=True)

        json_dir = os.path.dirname(self.data_file)
        if json_dir:
            os.makedirs(json_dir, exist_ok=True)

    def _connect(self):
        conn = sqlite3.connect(self.sqlite_file)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_database(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS records (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_records_timestamp ON records(timestamp)")

    def _get_meta(self, key, default=None):
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row['value'] if row else default

    def _set_meta(self, key, value):
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (key, str(value)),
            )

    def _record_count(self):
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM records").fetchone()
        return int(row['count']) if row else 0

    def _migrate_json_once(self):
        if self._get_meta('json_migrated') == '1':
            return

        imported = 0
        if os.path.exists(self.data_file) and os.path.getsize(self.data_file) > 0:
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    records = json.load(f)
                if isinstance(records, list):
                    for record in records:
                        if isinstance(record, dict) and record.get('id'):
                            self.save_record(record)
                            imported += 1
            except Exception as exc:
                print(f"旧JSON数据迁移失败，将继续使用SQLite: {exc}")

        self._set_meta('json_migrated', '1')
        if imported:
            print(f"已从旧JSON同步 {imported} 条考种记录到SQLite")

    def load_records(self):
        """Load all records as dictionaries."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT payload FROM records ORDER BY timestamp DESC, id DESC"
                ).fetchall()
            records = []
            for row in rows:
                try:
                    records.append(json.loads(row['payload']))
                except Exception:
                    continue
            return records
        except Exception as exc:
            print(f"加载数据失败: {exc}")
            return []

    def save_record(self, record):
        """Insert or update one record."""
        record_id = str(record.get('id', '')).strip()
        if not record_id:
            raise ValueError("record id is required")

        timestamp = str(record.get('timestamp', ''))
        payload = json.dumps(record, ensure_ascii=False)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO records (id, timestamp, payload)
                VALUES (?, ?, ?)
                """,
                (record_id, timestamp, payload),
            )

    def delete_record(self, record_id):
        """Delete one record and its image files."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT payload FROM records WHERE id = ?",
                    (record_id,),
                ).fetchone()
                if not row:
                    return False, "记录不存在"

                conn.execute("DELETE FROM records WHERE id = ?", (record_id,))

            image_path = os.path.join(self.images_folder, f"{record_id}.jpg")
            processed_path = os.path.join(self.processed_folder, f"{record_id}.jpg")
            for path in [image_path, processed_path]:
                if os.path.exists(path):
                    os.remove(path)

            return True, "删除成功"
        except Exception as exc:
            return False, f"删除失败: {str(exc)}"

    def delete_all_records(self):
        """Delete all records and image files."""
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM records")
                conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES ('json_migrated', '1')"
                )

            for folder in [self.images_folder, self.processed_folder]:
                if os.path.exists(folder):
                    for file in os.listdir(folder):
                        file_path = os.path.join(folder, file)
                        if os.path.isfile(file_path):
                            os.remove(file_path)

            return True, "所有数据已清空"
        except Exception as exc:
            return False, f"清空失败: {str(exc)}"

    def export_to_excel(self, output_path):
        """Export records to Excel or CSV."""
        try:
            records = self.load_records()
            if not records:
                return False, "没有数据可导出"

            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except PermissionError:
                    return False, f"导出失败: 文件已被打开，请先关闭文件\n{output_path}"
                except Exception as exc:
                    return False, f"导出失败: 无法删除旧文件\n{str(exc)}"

            desired_columns = [
                'id', 'timestamp', 'sample_code', 'count', 'avg_confidence',
                'avg_length', 'avg_width', 'avg_outer_side_length',
                'avg_inner_side_length', 'avg_curvature', 'avg_rect_length',
                'avg_rect_width', 'pixel_to_cm', 'source_type', 'source_path',
                'model_name', 'pod_measurements', 'image_path',
                'processed_image_path',
            ]
            columns = [
                column for column in desired_columns
                if any(column in record for record in records)
            ]
            rows = []
            for record in records:
                row = {}
                for column in columns:
                    value = record.get(column, '')
                    if isinstance(value, (list, dict)):
                        value = json.dumps(value, ensure_ascii=False)
                    row[column] = value
                rows.append(row)

            if output_path.lower().endswith('.csv'):
                with open(output_path, 'w', newline='', encoding='utf-8-sig') as file:
                    writer = csv.DictWriter(file, fieldnames=columns)
                    writer.writeheader()
                    writer.writerows(rows)
            else:
                from openpyxl import Workbook

                workbook = Workbook()
                worksheet = workbook.active
                worksheet.title = '豆荚测量数据'
                worksheet.append(columns)
                for row in rows:
                    worksheet.append([row.get(column, '') for column in columns])
                worksheet.freeze_panes = 'A2'
                worksheet.auto_filter.ref = worksheet.dimensions
                workbook.save(output_path)

            return True, f"导出成功: {output_path}"
        except PermissionError:
            return False, f"导出失败: 文件已被打开，请先关闭文件\n{output_path}"
        except Exception as exc:
            return False, f"导出失败: {str(exc)}"

    def create_pod_measurement_record(
        self,
        record_id,
        sample_code,
        summary,
        pod_measurements,
        source_type,
        source_path,
        model_name,
    ):
        """Build one JSON-serializable record for an analyzed photograph."""
        now = datetime.now()
        timestamp = now.strftime('%Y-%m-%d %H:%M:%S')

        image_path = os.path.abspath(os.path.join(self.images_folder, f"{record_id}.jpg"))
        processed_path = os.path.abspath(os.path.join(self.processed_folder, f"{record_id}.jpg"))

        return {
            'id': record_id,
            'timestamp': timestamp,
            'sample_code': sample_code,
            'model_name': model_name,
            'count': int(summary.get('count', 0)),
            'avg_confidence': round(float(summary.get('avg_confidence', 0)), 4),
            'avg_length': round(float(summary.get('avg_length', 0)), 4),
            'avg_width': round(float(summary.get('avg_width', 0)), 4),
            'avg_outer_side_length': round(
                float(summary.get('avg_outer_side_length', 0)), 4
            ),
            'avg_inner_side_length': round(
                float(summary.get('avg_inner_side_length', 0)), 4
            ),
            'avg_curvature': round(float(summary.get('avg_curvature', 0)), 3),
            'avg_rect_length': round(float(summary.get('avg_rect_length', 0)), 4),
            'avg_rect_width': round(float(summary.get('avg_rect_width', 0)), 4),
            'pixel_to_cm': round(float(summary.get('pixel_to_cm', 0)), 6),
            'source_type': source_type,
            'source_path': source_path,
            'pod_measurements': pod_measurements,
            'image_path': image_path,
            'processed_image_path': processed_path,
        }
