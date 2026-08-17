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
	"""List records in a table. Pass ?changed_only=true to list only records
	that differ from -- or don't exist in -- the editor's bundled default
	dataset, so the picker can default to "what did I actually touch" instead
	of every record in the table."""
	if request.method == 'GET':
		project_db = request.headers.get(rh.PROJECT_DB)
		datasets_db = request.headers.get(rh.DATASETS_DB)
		has_db, error = rh.init(project_db, datasets_db)
		if not has_db: abort(400, error)

		try:
			table = reference_submission.get_table(table_key)
		except ValueError as e:
			rh.close()
			abort(400, str(e))

		changed_only = request.args.get('changed_only') == 'true'

		if changed_only:
			if not datasets_db:
				rh.close()
				abort(400, 'Filtering by changed records requires the default dataset to be available.')
			items = reference_submission.list_changed_records(table_key)
		else:
			items = [
				{'id': m.id, 'name': m.name}
				for m in table.model.select(table.model.id, table.model.name).order_by(table.model.name)
			]

		rh.close()
		return jsonify({'records': items})

	abort(405, 'HTTP Method not allowed.')


@bp.route('/plan', methods=['POST'])
def plan():
	"""Work out what a batch of chosen records would change, given the current
	contents of each affected file upstream."""
	if request.method == 'POST':
		project_db = request.headers.get(rh.PROJECT_DB)
		has_db, error = rh.init(project_db)
		if not has_db: abort(400, error)

		args = request.get_json(silent=True) or {}
		items = args.get('items')
		existing_files = args.get('existing_files')

		if not isinstance(items, list):
			rh.close()
			abort(400, 'A list of records to submit is required.')
		if not isinstance(existing_files, dict):
			rh.close()
			abort(400, 'The current contents of each affected file are required.')

		result = reference_submission.plan_submission(items, existing_files)
		result['title'] = reference_submission.describe_submission(result['summary'], result['files'])
		rh.close()

		return jsonify(result)

	abort(405, 'HTTP Method not allowed.')
