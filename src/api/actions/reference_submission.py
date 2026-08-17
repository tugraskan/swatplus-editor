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

from peewee import CharField, TextField, ForeignKeyField, BooleanField

from database.project import hru_parm_db as project_parmdb
from database.project import ops as project_ops
from database.project import structural as project_structural
from database.project import lum as project_lum
from fileio import hru_parm_db as files_parmdb
from fileio import ops as files_ops
from fileio import structural as files_structural
from fileio import lum as files_lum


class SubmittableTable:
	def __init__(self, key, label, file_name, model, file_model, docs_path):
		self.key = key
		self.label = label
		self.file_name = file_name
		self.model = model
		self.file_model = file_model
		self.docs_path = docs_path


# Field types that hold text or a reference rather than a plain number --
# e.g. plants.plt's plnt_typ/gro_trig, fertilizer.frt's pathogens. Everything
# else is treated as numeric, since these tables are otherwise all DoubleField.
_NON_NUMERIC_FIELD_TYPES = (CharField, TextField, ForeignKeyField, BooleanField)


def _numeric_columns(table):
	"""True/False per body column, aligned with a written row's columns (id
	excluded, same as the writer), for whether that column's underlying field
	is a plain number. The writer builds one column per non-id field in
	table.model's declared order, so this lines up with it by construction."""
	return [
		not isinstance(field, _NON_NUMERIC_FIELD_TYPES)
		for field in table.model._meta.sorted_fields
		if field.name != 'id'
	]


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

	SubmittableTable('graze', 'Graze', 'graze.ops',
					 project_ops.Graze_ops, files_ops.Graze_ops, 'management-practices/graze.ops'),
	SubmittableTable('harvest', 'Harvest', 'harv.ops',
					 project_ops.Harv_ops, files_ops.Harv_ops, 'management-practices/harv.ops'),
	SubmittableTable('irrigation', 'Irrigation', 'irr.ops',
					 project_ops.Irr_ops, files_ops.Irr_ops, 'management-practices/irr.ops'),
	SubmittableTable('fire', 'Fire', 'fire.ops',
					 project_ops.Fire_ops, files_ops.Fire_ops, 'management-practices/fire.ops'),
	SubmittableTable('sweep', 'Sweep', 'sweep.ops',
					 project_ops.Sweep_ops, files_ops.Sweep_ops, 'management-practices/sweep.ops'),
	SubmittableTable('chem_app', 'Chemical Applications', 'chem_app.ops',
					 project_ops.Chem_app_ops, files_ops.Chem_app_ops, 'management-practices/chem_app.ops'),

	SubmittableTable('septic_str', 'Septic Systems', 'septic.str',
					 project_structural.Septic_str, files_structural.Septic_str, 'structural-practices/septic.str'),
	SubmittableTable('bmpuser', 'User Best Management Practices', 'bmpuser.str',
					 project_structural.Bmpuser_str, files_structural.Bmpuser_str, 'structural-practices/bmpuser.str'),
	SubmittableTable('filterstrip', 'Filter Strips', 'filterstrip.str',
					 project_structural.Filterstrip_str, files_structural.Filterstrip_str, 'structural-practices/filterstrip.str'),
	SubmittableTable('grassedww', 'Grassed Waterways', 'grassedww.str',
					 project_structural.Grassedww_str, files_structural.Grassedww_str, 'structural-practices/grassedww.str'),
	SubmittableTable('tiledrain', 'Tile Drains', 'tiledrain.str',
					 project_structural.Tiledrain_str, files_structural.Tiledrain_str, 'structural-practices/tiledrain.str'),

	SubmittableTable('cntable', 'Curve Numbers', 'cntable.lum',
					 project_lum.Cntable_lum, files_lum.Cntable_lum, 'landuse-and-management/cntable.lum'),
	SubmittableTable('ovn_table', "Manning's n Tables", 'ovn_table.lum',
					 project_lum.Ovn_table_lum, files_lum.Ovn_table_lum, 'landuse-and-management/ovn_table.lum'),
	SubmittableTable('cons_practice', 'Conservation Practices', 'cons_practice.lum',
					 project_lum.Cons_prac_lum, files_lum.Cons_prac_lum, 'landuse-and-management/cons_practice.lum'),
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


def _write_table_to_text(table, database='project'):
	"""Run the editor's own writer for this table into a temp file and return
	its lines. Uses write() so every per-file quirk the writer applies --
	description formatting, precision and padding overrides, row ordering --
	is applied exactly as it would be for a real file write. `database` selects
	the project's own table or the editor's bundled default dataset -- both are
	written by the identical code path, so a row from either is comparable."""
	handle, path = tempfile.mkstemp(suffix='-' + table.file_name)
	os.close(handle)
	try:
		table.file_model(path).write(database=database)
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
		'numeric_columns': _numeric_columns(table),
	}




def _is_number(value):
	try:
		float(value)
		return True
	except ValueError:
		return False


# The first two lines of every file are the "written by" line and the column
# header; record rows start after them.
HEADER_LINE_COUNT = 2


def _record_rows(text):
	"""Map record name -> its line, for the record rows of a file."""
	rows = {}
	for line in text.splitlines()[HEADER_LINE_COUNT:]:
		fields = line.split()
		if fields:
			rows.setdefault(fields[0], line)
	return rows


def _rows_from_lines(lines):
	"""Same as _record_rows, for a writer's output already split into lines."""
	rows = {}
	for line in lines[HEADER_LINE_COUNT:]:
		fields = line.split()
		if fields:
			rows.setdefault(fields[0], line)
	return rows


def list_changed_records(table_key):
	"""Records in the project whose formatted row differs from -- or has no
	counterpart in -- the editor's own bundled default dataset for this table.
	A heuristic for "records the user likely added or changed themselves",
	meant to narrow the record picker instead of listing every record in the
	table (most of which, in most projects, are untouched stock defaults).

	This compares against the *local* default dataset shipped with this copy
	of the editor, not the reference database on GitHub -- the two can differ
	if the reference database has moved on since this dataset was built. That
	makes it a good proxy for "did I touch this", but not a substitute for the
	real check against GitHub, which still happens when a record is reviewed
	for submission.
	"""
	table = get_table(table_key)

	project_rows = _rows_from_lines(_write_table_to_text(table, database='project'))
	default_rows = _rows_from_lines(_write_table_to_text(table, database='datasets'))

	changed = []
	for record in table.model.select(table.model.id, table.model.name).order_by(table.model.name):
		project_row = project_rows.get(record.name)
		if project_row is None:
			# The writer skipped or renamed this record on the way out (e.g. a
			# blank name); nothing to compare it against.
			continue

		default_row = default_rows.get(record.name)
		if default_row is None:
			operation = 'add'
		elif default_row.rstrip() != project_row.rstrip():
			operation = 'update'
		else:
			continue  # matches the shipped default untouched -- not a change

		changed.append({'id': record.id, 'name': record.name, 'operation': operation})

	return changed


def _apply_rows(text, replacements, additions):
	"""Rewrite a file with some rows replaced in place and others appended.

	Replacing in place rather than removing and re-appending is what keeps an
	update to an existing record a one-line diff instead of a two-line move.
	"""
	lines = text.splitlines()
	out = []
	for index, line in enumerate(lines):
		fields = line.split()
		if index >= HEADER_LINE_COUNT and fields and fields[0] in replacements:
			out.append(replacements[fields[0]])
		else:
			out.append(line)

	out.extend(additions)
	return '\n'.join(out) + '\n'


def _validate_row(serialized, upstream_columns=None):
	"""Check one formatted row. Whether the record already exists upstream is
	decided by the caller -- an existing name is an update here, not an error."""
	errors = []
	warnings = []

	name = serialized['record_name']
	columns = serialized['columns']
	numeric_columns = serialized.get('numeric_columns')
	fields = serialized['row_line'].split()

	if name is None or name.strip() == '' or name.strip().lower() == 'null':
		errors.append("Record name is blank or 'null'. Give the record a real name before submitting.")

	if name is not None and any(character.isspace() for character in name):
		errors.append('Record name "{}" contains whitespace, which would split into extra columns.'.format(name))

	# The trailing description column is free text that may contain spaces or be
	# absent entirely, so it is excluded from strict field counting.
	required_field_count = max(len(columns) - 1, 1)
	if len(fields) < required_field_count:
		errors.append('Row has {} fields but {} expects at least {}.'.format(
			len(fields), serialized['file_name'], required_field_count))

	for index in range(1, min(len(fields), required_field_count)):
		value = fields[index]
		column_name = columns[index] if index < len(columns) else 'column {}'.format(index + 1)
		if value.lower() == 'null':
			continue
		# A category or reference column (e.g. plants.plt's plnt_typ, fertilizer.frt's
		# pathogens) is expected to hold text, not a number.
		if numeric_columns is not None and index < len(numeric_columns) and not numeric_columns[index]:
			continue
		if not _is_number(value):
			errors.append("Non-numeric value '{}' in column '{}'.".format(value, column_name))

	if upstream_columns is not None and upstream_columns != columns:
		missing = [c for c in upstream_columns if c not in columns]
		new = [c for c in columns if c not in upstream_columns]
		errors.append(
			'Column headers do not match {} in the reference database '
			'(missing: {}, new: {}). This usually means the editor and the reference '
			'database are on different SWAT+ revisions.'.format(serialized['file_name'], missing, new))

	if len(fields) == required_field_count:
		warnings.append('This record has no description. A short description helps reviewers.')

	return errors, warnings


def plan_submission(items, existing_files):
	"""Work out what a batch of records would do to the reference database.

	`items` is a list of {'table': key, 'id': record id}; `existing_files` maps
	a file name to its current contents upstream. Each record is classified as
	an addition, an update, or unchanged, and the resulting contents are built
	per file so that one pull request can carry several records across several
	files.
	"""
	results = []
	submission_errors = []
	upstream_rows = {name: _record_rows(text) for name, text in existing_files.items()}

	# Per file: name -> replacement line, and the list of lines to append.
	replacements = {}
	additions = {}
	seen = {}

	for item in items:
		table_key = item.get('table')
		record_id = item.get('id')

		try:
			serialized = serialize_record(table_key, record_id)
		except ValueError as e:
			submission_errors.append(str(e))
			continue

		file_name = serialized['file_name']
		name = serialized['record_name']
		text = existing_files.get(file_name)

		if text is None:
			submission_errors.append(
				'The current contents of {} were not supplied, so this record could not be checked.'.format(file_name))
			continue

		upstream_columns = None
		upstream_lines = text.splitlines()
		if len(upstream_lines) >= HEADER_LINE_COUNT:
			upstream_columns = upstream_lines[1].split()

		errors, warnings = _validate_row(serialized, upstream_columns)

		key = (file_name, name)
		if key in seen:
			errors.append(
				'"{}" is in this submission more than once. Each record can only be '
				'submitted once per file.'.format(name))
		seen[key] = True

		existing_row = upstream_rows.get(file_name, {}).get(name)
		if existing_row is None:
			operation = 'add'
		elif existing_row.rstrip() == serialized['row_line'].rstrip():
			operation = 'unchanged'
			warnings.append('This record already matches the reference database, so it will not be included.')
		else:
			operation = 'update'

		result = dict(serialized)
		result['operation'] = operation
		result['existing_row_line'] = existing_row
		result['errors'] = errors
		result['warnings'] = warnings
		result['valid'] = len(errors) == 0
		results.append(result)

		if errors or operation == 'unchanged':
			continue

		if operation == 'update':
			replacements.setdefault(file_name, {})[name] = serialized['row_line']
		else:
			additions.setdefault(file_name, []).append(serialized['row_line'])

	changed_file_names = set(replacements) | set(additions)
	files = [
		{
			'file_name': file_name,
			'contents': _apply_rows(
				existing_files[file_name],
				replacements.get(file_name, {}),
				additions.get(file_name, []))
		}
		for file_name in sorted(changed_file_names)
	]

	if not items:
		submission_errors.append('Choose at least one record to submit.')
	elif not files and not submission_errors and all(r['valid'] for r in results):
		submission_errors.append('Nothing to submit -- every record chosen already matches the reference database.')

	summary = {
		'added': sum(1 for r in results if r['operation'] == 'add' and r['valid']),
		'updated': sum(1 for r in results if r['operation'] == 'update' and r['valid']),
		'unchanged': sum(1 for r in results if r['operation'] == 'unchanged'),
	}

	return {
		'items': results,
		'files': files,
		'errors': submission_errors,
		'summary': summary,
		'valid': not submission_errors and all(r['valid'] for r in results) and len(files) > 0,
	}


def describe_submission(summary, files):
	"""Short title for the commit and the pull request."""
	parts = []
	if summary['added']:
		parts.append('{} record{}'.format(summary['added'], '' if summary['added'] == 1 else 's'))
	change = []
	if parts:
		change.append('Add ' + parts[0])
	if summary['updated']:
		change.append('update {} record{}'.format(summary['updated'], '' if summary['updated'] == 1 else 's'))

	file_names = ', '.join(f['file_name'] for f in files)
	action = ' and '.join(change) if change else 'Update records'
	return '{} in {}'.format(action, file_names)
