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
