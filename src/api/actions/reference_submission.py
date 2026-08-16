"""Serialize a single project database record into the exact SWAT+ text form
used by the authoritative reference database repository, and check it against
the same rules that repository's CI enforces.

The reference repository's files are produced by this editor's own writers --
every file there carries a "written by SWAT+ editor" header line. So rather
than reformat a row by hand, this module runs the real writer over the table,
into a temporary file, and lifts out the header and the one line belonging to
the record being submitted. That keeps a submitted line byte-identical to the
line the same record would occupy had the whole file been regenerated, which
is what keeps the resulting pull request a one-line diff.

The validation here deliberately mirrors the reference repository's
validate_database_files.py (field counts, numeric columns, blank/'null' record
names, duplicate names, column-header drift). It is a pre-flight check, not a
replacement: catching these locally means a contributor sees the problem in the
editor instead of as a red pull request.
"""

import os
import tempfile

from database.project import hru_parm_db as project_parmdb
from fileio import hru_parm_db as files_parmdb


class SubmittableTable:
	def __init__(self, key, label, file_name, model, file_model, docs_path):
		self.key = key
		self.label = label
		self.file_name = file_name
		self.model = model
		self.file_model = file_model
		self.docs_path = docs_path


# Tables the editor's database section exposes that the reference repository
# also maintains text for. septic.sep is deliberately absent -- see
# UNSUPPORTED_TABLES below.
SUBMITTABLE_TABLES = [
	SubmittableTable('plants', 'Plants', 'plants.plt',
					 project_parmdb.Plants_plt, files_parmdb.Plants_plt, 'databases/plants.plt'),
	SubmittableTable('fertilizer', 'Fertilizer', 'fertilizer.frt',
					 project_parmdb.Fertilizer_frt, files_parmdb.Fertilizer_frt, 'databases/fertilzer.frt'),
	SubmittableTable('tillage', 'Tillage', 'tillage.til',
					 project_parmdb.Tillage_til, files_parmdb.Tillage_til, 'databases/tillage.til'),
	SubmittableTable('pesticides', 'Pesticides', 'pesticide.pes',
					 project_parmdb.Pesticide_pst, files_parmdb.Pesticide_pst, 'databases/pesticide.pes'),
	SubmittableTable('urban', 'Urban', 'urban.urb',
					 project_parmdb.Urban_urb, files_parmdb.Urban_urb, 'databases/urban.urb'),
	SubmittableTable('snow', 'Snow', 'snow.sno',
					 project_parmdb.Snow_sno, files_parmdb.Snow_sno, 'databases/snow.sno'),
]

# Reported to the user so an absent table reads as a known limitation rather
# than an oversight. Both entries match EXCLUDED_TABLES in the reference
# repository's internal/scripts/patch_editor_dataset.py: a record submitted for
# either one could never be synced back into the editor's dataset, because the
# editor's own reader for it is broken.
UNSUPPORTED_TABLES = {
	'septic.sep': (
		"The editor's Septic_sep.read() expects 13 whitespace-delimited columns "
		"but the real septic_sep schema has 12, so an accepted record could not "
		"be read back into the editor's dataset. Fix the reader upstream first."
	),
	'cal_parms.cal': (
		"The editor's Cal_parms_cal.read() force-lowercases parameter names, "
		"which would silently rename mixed-case parameters on the way back in."
	),
	'pathogens.pth': (
		"The reference database's pathogens.pth comes from an external source "
		"(bacteria.bac) rather than the SWAT+ Editor dataset, and is stored in "
		"that source's column format, not the format this editor writes. It is "
		"marked 'needs_review' upstream; propose changes to it directly."
	),
}

TABLES_BY_KEY = {t.key: t for t in SUBMITTABLE_TABLES}


def get_table(key):
	table = TABLES_BY_KEY.get(key)
	if table is None:
		raise ValueError('{} is not a table that can be submitted to the reference database.'.format(key))
	return table


def _write_table_to_text(table):
	"""Run the editor's own writer for this table into a temp file and return
	its lines. Uses write() so every per-file quirk the writer applies --
	description formatting, precision and padding overrides, row ordering --
	is applied exactly as it would be for a real file write."""
	handle, path = tempfile.mkstemp(suffix='-' + table.file_name)
	os.close(handle)
	try:
		table.file_model(path).write()
		with open(path, 'r') as file:
			return file.read().splitlines()
	finally:
		if os.path.exists(path):
			os.remove(path)


def serialize_record(table_key, record_id):
	"""Return the metadata line, column header line, and the single formatted
	text line for one record, exactly as the reference repository stores it."""
	table = get_table(table_key)

	record = table.model.get_or_none(table.model.id == record_id)
	if record is None:
		raise ValueError('{} record {} does not exist.'.format(table.label, record_id))

	name = record.name
	lines = _write_table_to_text(table)
	if len(lines) < 2:
		raise ValueError('{} produced no rows to submit.'.format(table.file_name))

	meta_line = lines[0]
	header_line = lines[1]

	row_line = None
	for line in lines[2:]:
		fields = line.split()
		if fields and fields[0] == name:
			row_line = line
			break

	if row_line is None:
		raise ValueError(
			'Could not locate record "{}" in the generated {}. '
			'The record may have a name the writer alters.'.format(name, table.file_name))

	return {
		'table': table.key,
		'label': table.label,
		'file_name': table.file_name,
		'record_id': record_id,
		'record_name': name,
		'meta_line': meta_line,
		'header_line': header_line,
		'row_line': row_line,
		'columns': header_line.split(),
	}


def _is_number(value):
	try:
		float(value)
		return True
	except ValueError:
		return False


def validate_row(serialized, existing_file_text=None):
	"""Check a serialized row the way the reference repository's CI does.

	Returns (errors, warnings). Errors block submission; warnings do not.
	When the current contents of the target file are supplied, the record name
	is also checked for collision and the column header for drift -- the two
	failures that depend on the file as it exists upstream rather than on the
	row alone.
	"""
	errors = []
	warnings = []

	name = serialized['record_name']
	row_line = serialized['row_line']
	columns = serialized['columns']

	if name is None or name.strip() == '' or name.strip().lower() == 'null':
		errors.append("Record name is blank or 'null'. Give the record a real name before submitting.")

	if name is not None and any(character.isspace() for character in name):
		errors.append('Record name "{}" contains whitespace, which would split into extra columns.'.format(name))

	fields = row_line.split()
	# The trailing description column is free text that may contain spaces or
	# be absent entirely, so it is excluded from strict field counting.
	required_field_count = max(len(columns) - 1, 1)
	if len(fields) < required_field_count:
		errors.append('Row has {} fields but {} expects at least {}.'.format(
			len(fields), serialized['file_name'], required_field_count))

	# Every column between the leading name and the trailing description is
	# numeric in these files; a non-numeric value there is what the reference
	# repository's validator rejects as a wrong data type.
	for index in range(1, min(len(fields), required_field_count)):
		value = fields[index]
		column_name = columns[index] if index < len(columns) else 'column {}'.format(index + 1)
		if value.lower() == 'null':
			continue
		if not _is_number(value):
			errors.append("Non-numeric value '{}' in column '{}'.".format(value, column_name))

	if existing_file_text is not None:
		existing_lines = existing_file_text.splitlines()
		if len(existing_lines) >= 2:
			upstream_columns = existing_lines[1].split()
			if upstream_columns != columns:
				missing = [c for c in upstream_columns if c not in columns]
				new = [c for c in columns if c not in upstream_columns]
				errors.append(
					'Column headers do not match {} in the reference database '
					'(missing: {}, new: {}). This usually means the editor and the '
					'reference database are on different SWAT+ revisions.'.format(
						serialized['file_name'], missing, new))

			for line in existing_lines[2:]:
				existing_fields = line.split()
				if existing_fields and existing_fields[0] == name:
					errors.append(
						'The reference database already has a record named "{}" in {}. '
						'Submitting it again would create a duplicate; rename your record '
						'or propose an edit to the existing one instead.'.format(name, serialized['file_name']))
					break

	if len(fields) == required_field_count:
		warnings.append('This record has no description. A short description helps reviewers.')

	return errors, warnings


def build_file_contents(existing_file_text, row_line):
	"""Append the row to the file's existing contents, preserving the trailing
	newline convention so the diff is exactly one added line."""
	if existing_file_text.endswith('\n'):
		return existing_file_text + row_line + '\n'
	return existing_file_text + '\n' + row_line + '\n'
