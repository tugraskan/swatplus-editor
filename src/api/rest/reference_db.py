"""Endpoints backing the "contribute a record to the reference database"
workflow. These only prepare and check the text of a submission -- the GitHub
side of it happens in the main process, so no credential ever reaches the API.
"""

from flask import Blueprint, request, abort, jsonify
from .config import RequestHeaders as rh

from actions import reference_submission

bp = Blueprint('reference_db', __name__, url_prefix='/reference-db')


@bp.route('/tables', methods=['GET'])
def tables():
	if request.method == 'GET':
		return jsonify({
			'tables': [
				{
					'key': t.key,
					'label': t.label,
					'file_name': t.file_name,
					'docs_path': t.docs_path
				} for t in reference_submission.SUBMITTABLE_TABLES
			],
			'unsupported': [
				{'file_name': name, 'reason': reason}
				for name, reason in reference_submission.UNSUPPORTED_TABLES.items()
			]
		})

	abort(405, 'HTTP Method not allowed.')


@bp.route('/records/<table_key>', methods=['GET'])
def records(table_key):
	if request.method == 'GET':
		project_db = request.headers.get(rh.PROJECT_DB)
		has_db, error = rh.init(project_db)
		if not has_db: abort(400, error)

		try:
			table = reference_submission.get_table(table_key)
		except ValueError as e:
			rh.close()
			abort(400, str(e))

		items = [
			{'id': m.id, 'name': m.name}
			for m in table.model.select(table.model.id, table.model.name).order_by(table.model.name)
		]
		rh.close()
		return jsonify({'records': items})

	abort(405, 'HTTP Method not allowed.')


@bp.route('/preview', methods=['POST'])
def preview():
	if request.method == 'POST':
		project_db = request.headers.get(rh.PROJECT_DB)
		has_db, error = rh.init(project_db)
		if not has_db: abort(400, error)

		args = request.get_json(silent=True) or {}
		table_key = args.get('table')
		record_id = args.get('id')
		existing_file_text = args.get('existing_file_text')

		if table_key is None or record_id is None:
			rh.close()
			abort(400, 'Both a table and a record id are required.')

		try:
			serialized = reference_submission.serialize_record(table_key, record_id)
		except ValueError as e:
			rh.close()
			abort(400, str(e))

		errors, warnings = reference_submission.validate_row(serialized, existing_file_text)
		rh.close()

		result = dict(serialized)
		result['errors'] = errors
		result['warnings'] = warnings
		result['valid'] = len(errors) == 0

		if existing_file_text is not None and len(errors) == 0:
			result['file_contents'] = reference_submission.build_file_contents(
				existing_file_text, serialized['row_line'])

		return jsonify(result)

	abort(405, 'HTTP Method not allowed.')
