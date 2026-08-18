<script setup lang="ts">
	// Propose records from this project for the SWAT+ reference database as one pull
	// request. Records are staged first so a submission can span several files, and
	// each is classified against the reference database as an add, update or
	// unchanged. Rows are formatted by the editor's own writers via the API;
	// authentication and the GitHub calls happen in the main process.
	import { computed, reactive, ref, watch } from 'vue';
	import { useHelpers } from '@/helpers';
	import type { ReferenceDbPlan, ReferenceDbPullRequest, ReferenceDbTable } from '@/typings';

	const { api, constants, currentProject, errors, utilities } = useHelpers();
	const electron = window.electronApi;

	interface StagedRecord {
		table: string;
		tableLabel: string;
		fileName: string;
		id: number;
		name: string;
	}

	const show = ref(false);
	const step = ref(1);

	const page = reactive({
		loading: false,
		error: null as string | null,
		submitting: false
	});

	const repo = reactive({ owner: '', repo: '', branch: 'main' });
	const repoUrl = computed(() => `https://github.com/${repo.owner}/${repo.repo}`);

	const auth = reactive({
		checking: false,
		authenticated: false,
		login: '',
		deviceFlowAvailable: false,
		encryptionAvailable: true,
		tokenInPlaintext: false,
		error: null as string | null
	});

	const device = reactive({
		active: false,
		userCode: '',
		verificationUri: '',
		waiting: false
	});

	const patToken = ref('');
	const showToken = ref(false);

	const tables = ref<ReferenceDbTable[]>([]);
	const unsupported = ref<{ file_name: string, reason: string }[]>([]);
	const records = ref<{ id: number, name: string, operation?: 'add' | 'update' }[]>([]);

	// Whether the last load actually applied the filter, kept separate from the
	// toggle so a fallback to the full list is not reported as filtered.
	const recordsAreFiltered = ref(false);

	const picker = reactive({
		table: null as string | null,
		recordIds: [] as number[],
		onlyChanged: true
	});

	const hasDefaultDataset = computed(() => !!currentProject.datasetsDb);

	const staged = ref<StagedRecord[]>([]);
	const details = reactive({ reason: '', source: '', notes: '' });

	const plan = ref<ReferenceDbPlan | null>(null);
	// Blob sha each file was read at, so an upstream change made in between is
	// caught rather than overwritten.
	const fileShas = ref<Record<string, string>>({});

	interface PullRequestOutcome {
		fileName: string;
		ok: boolean;
		data?: ReferenceDbPullRequest;
		error?: string;
	}
	const results = ref<PullRequestOutcome[]>([]);
	const submitProgress = ref('');

	const selectedTable = computed(() => tables.value.find(t => t.key === picker.table) || null);
	const canStage = computed(() => picker.table !== null && picker.recordIds.length > 0);
	const canReview = computed(() => staged.value.length > 0);
	const canSubmit = computed(() =>
		auth.authenticated && plan.value !== null && plan.value.valid && !page.submitting);
	const pullRequestCount = computed(() => plan.value ? plan.value.files.length : 0);

	// Only tables with records the user has added or changed, unless the toggle
	// is off or no default dataset is available to compare against.
	const visibleTables = computed(() => {
		if (!picker.onlyChanged || !hasDefaultDataset.value) return tables.value;
		return tables.value.filter(t => (t.changed_count || 0) > 0);
	});

	const tableItems = computed(() => visibleTables.value.map(t => ({
		...t,
		displayLabel: t.changed_count !== undefined ? `${t.label} (${t.changed_count})` : t.label
	})));

	// Records already staged should not be offered again.
	const availableRecords = computed(() => {
		const taken = new Set(staged.value.filter(s => s.table === picker.table).map(s => s.id));
		return records.value.filter(r => !taken.has(r.id));
	});

	const stagedByFile = computed(() => {
		const groups: Record<string, StagedRecord[]> = {};
		for (const record of staged.value) {
			if (groups[record.fileName] === undefined) groups[record.fileName] = [];
			groups[record.fileName].push(record);
		}
		return groups;
	});

	function operationColor(operation: string) {
		if (operation === 'add') return 'success';
		if (operation === 'update') return 'info';
		return 'medium-emphasis';
	}

	function operationLabel(operation: string) {
		if (operation === 'add') return 'New';
		if (operation === 'update') return 'Update';
		return 'No change';
	}

	async function open() {
		show.value = true;
		step.value = 1;
		results.value = [];
		plan.value = null;
		staged.value = [];
		picker.table = null;
		picker.recordIds = [];
		details.reason = '';
		details.source = '';
		details.notes = '';
		page.error = null;

		const config = await electron.referenceDbConfig();
		Object.assign(repo, config);

		await Promise.all([loadTables(), checkAuth()]);
	}

	async function loadTables() {
		page.loading = true;
		try {
			const useFilter = picker.onlyChanged && hasDefaultDataset.value;
			const url = 'reference-db/tables' + (useFilter ? '?changed_only=true' : '');
			const response = await api.get(url, currentProject.getApiHeader());
			tables.value = response.data.tables;
			unsupported.value = response.data.unsupported;
		} catch (error) {
			page.error = errors.logError(error, 'Unable to load the list of contributable tables.');
		}
		page.loading = false;
	}

	async function checkAuth() {
		auth.checking = true;
		auth.error = null;
		const response = await electron.referenceDbAuthStatus();
		if (response.ok && response.data) {
			auth.authenticated = response.data.authenticated;
			auth.login = response.data.login || '';
			auth.deviceFlowAvailable = response.data.deviceFlowAvailable;
			auth.encryptionAvailable = response.data.encryptionAvailable;
			auth.tokenInPlaintext = response.data.tokenInPlaintext || false;
		} else {
			auth.error = response.error || 'Unable to check GitHub sign-in status.';
		}
		auth.checking = false;
	}

	async function signInWithToken() {
		auth.error = null;
		auth.checking = true;
		const response = await electron.referenceDbSignInToken(patToken.value);
		if (response.ok && response.data) {
			patToken.value = '';
			auth.authenticated = true;
			auth.login = response.data.login;
			auth.tokenInPlaintext = response.data.tokenInPlaintext;
		} else {
			auth.error = response.error || 'Sign-in failed.';
		}
		auth.checking = false;
	}

	async function startDeviceFlow() {
		auth.error = null;
		const started = await electron.referenceDbDeviceStart();
		if (!started.ok || !started.data) {
			auth.error = started.error || 'Unable to start GitHub sign-in.';
			return;
		}

		device.active = true;
		device.userCode = started.data.userCode;
		device.verificationUri = started.data.verificationUri;
		device.waiting = true;
		utilities.openUrl(started.data.verificationUri);

		const finished = await electron.referenceDbDevicePoll(
			started.data.deviceCode, started.data.interval, started.data.expiresIn);

		device.waiting = false;
		device.active = false;
		if (finished.ok && finished.data) {
			auth.authenticated = true;
			auth.login = finished.data.login;
			auth.tokenInPlaintext = finished.data.tokenInPlaintext;
		} else {
			auth.error = finished.error || 'Sign-in failed.';
		}
	}

	async function signOut() {
		await electron.referenceDbSignOut();
		auth.authenticated = false;
		auth.login = '';
	}

	async function loadRecords() {
		records.value = [];
		picker.recordIds = [];
		if (picker.table === null) return;

		const useFilter = picker.onlyChanged && hasDefaultDataset.value;
		const url = `reference-db/records/${picker.table}` + (useFilter ? '?changed_only=true' : '');

		page.loading = true;
		try {
			const response = await api.get(url, currentProject.getApiHeader());
			records.value = response.data.records;
			recordsAreFiltered.value = useFilter;
		} catch (error) {
			page.error = errors.logError(error, 'Unable to load records for this table.');
		}
		page.loading = false;
	}

	function stageSelected() {
		if (selectedTable.value === null) return;
		for (const id of picker.recordIds) {
			const record = records.value.find(r => r.id === id);
			if (record === undefined) continue;
			staged.value.push({
				table: selectedTable.value.key,
				tableLabel: selectedTable.value.label,
				fileName: selectedTable.value.file_name,
				id: record.id,
				name: record.name
			});
		}
		picker.recordIds = [];
		plan.value = null;
	}

	function unstage(record: StagedRecord) {
		staged.value = staged.value.filter(s => !(s.table === record.table && s.id === record.id));
		plan.value = null;
	}

	// Read each affected file as it stands upstream, then have the API work out what
	// the staged records would do to it, so updates, no-op records and column drift
	// are identified before anything is pushed to GitHub.
	async function buildPlan() {
		if (!canReview.value) return;

		page.loading = true;
		page.error = null;
		plan.value = null;
		fileShas.value = {};

		const existingFiles: Record<string, string> = {};
		for (const fileName of Object.keys(stagedByFile.value)) {
			const file = await electron.referenceDbGetFile(`database_files/${fileName}`);
			if (!file.ok || !file.data) {
				page.error = file.error || `Unable to read ${fileName} from the reference database.`;
				page.loading = false;
				return;
			}
			existingFiles[fileName] = file.data.text;
			fileShas.value[fileName] = file.data.sha;
		}

		try {
			const response = await api.post('reference-db/plan', {
				items: staged.value.map(s => ({ table: s.table, id: s.id })),
				existing_files: existingFiles
			}, currentProject.getApiHeader());
			plan.value = response.data;
			step.value = 2;
		} catch (error) {
			page.error = errors.logError(error, 'Unable to prepare these records for submission.');
		}
		page.loading = false;
	}

	// Opens one pull request per file, so a reviewer for fertilizer.frt is not
	// also asked to weigh in on an unrelated tillage.til change, and one file
	// can be merged without waiting on another. Requests run one at a time,
	// and every file is attempted even if an earlier one fails, so the result
	// list always reflects what actually happened to each file.
	async function submit() {
		if (!canSubmit.value || plan.value === null) return;

		page.submitting = true;
		page.error = null;
		results.value = [];

		for (const [index, file] of plan.value.files.entries()) {
			submitProgress.value = `Opening pull request ${index + 1} of ${plan.value.files.length} (${file.file_name})...`;

			const fileItems = plan.value.items.filter(i =>
				i.file_name === file.file_name && i.operation !== 'unchanged' && i.valid);

			const response = await electron.referenceDbSubmit({
				files: [{
					path: `database_files/${file.file_name}`,
					contents: file.contents,
					baseSha: fileShas.value[file.file_name]
				}],
				title: plan.value.file_titles[file.file_name] || plan.value.title,
				records: fileItems.map(i => `${operationLabel(i.operation)}: \`${i.record_name}\``),
				reason: details.reason,
				source: details.source,
				notes: details.notes,
				editorVersion: constants.appSettings.version
			});

			if (response.ok && response.data) {
				results.value.push({ fileName: file.file_name, ok: true, data: response.data });
			} else {
				results.value.push({ fileName: file.file_name, ok: false, error: response.error || 'Unable to open the pull request.' });
			}
		}

		submitProgress.value = '';
		step.value = 3;
		page.submitting = false;
	}

	function close() {
		show.value = false;
		device.active = false;
	}

	watch(() => picker.table, async () => await loadRecords());
	watch(() => picker.onlyChanged, async () => {
		// If the selected table drops out of view, clear it -- that alone
		// triggers the watcher above, which clears the record list too.
		if (picker.table !== null && !visibleTables.value.some(t => t.key === picker.table)) {
			picker.table = null;
		} else {
			await loadRecords();
		}
	});

	defineExpose({ open });
</script>

<template>
	<v-list-item @click="open" border="t" class="text-primary">
		<template #prepend><v-icon class="text-medium-emphasis">fas fa-code-pull-request</v-icon></template>
		Contribute Records to the Reference Database
	</v-list-item>

	<v-dialog v-model="show" :max-width="constants.dialogSizes.lg" scrollable>
		<v-card>
			<v-card-title>Contribute Records to the Reference Database</v-card-title>

			<v-card-text>
				<error-alert :text="page.error"></error-alert>

				<!-- Step 1: sign in, then stage the records to submit -->
				<div v-if="step === 1">
					<p class="text-medium-emphasis mb-4">
						Propose records from this project for inclusion in the
						<open-in-browser :url="repoUrl" :text="`${repo.owner}/${repo.repo}`" class="text-primary"></open-in-browser>
						reference database. Add as many as you like, from as many tables as you like. They go out together as
						one pull request. A reviewer there decides whether to merge it.
					</p>

					<v-card variant="tonal" class="mb-4">
						<v-card-text>
							<div v-if="auth.checking" class="d-flex align-center">
								<v-progress-circular indeterminate size="20" width="2" class="mr-3"></v-progress-circular>
								Checking GitHub sign-in...
							</div>

							<div v-else-if="auth.authenticated" class="d-flex align-center justify-space-between">
								<div>
									<v-icon class="text-success mr-2">fas fa-circle-check</v-icon>
									Signed in to GitHub as <strong>{{ auth.login }}</strong>
								</div>
								<v-btn variant="text" size="small" @click="signOut">Sign out</v-btn>
							</div>

							<div v-else>
								<error-alert :text="auth.error"></error-alert>
								<p class="mb-3">Sign in to GitHub to open a pull request.</p>

								<div v-if="device.active" class="mb-3">
									<p class="mb-2">
										Enter this code at
										<open-in-browser :url="device.verificationUri" :text="device.verificationUri" class="text-primary"></open-in-browser>:
									</p>
									<p class="text-h5 font-monospace mb-2">{{ device.userCode }}</p>
									<div v-if="device.waiting" class="d-flex align-center text-medium-emphasis">
										<v-progress-circular indeterminate size="18" width="2" class="mr-2"></v-progress-circular>
										Waiting for you to approve in the browser...
									</div>
								</div>

								<template v-else>
									<v-btn v-if="auth.deviceFlowAvailable" color="primary" variant="flat" class="mb-3" @click="startDeviceFlow">
										Sign in with GitHub
									</v-btn>

									<div>
										<p class="text-medium-emphasis mb-2">
											<template v-if="auth.deviceFlowAvailable">Or paste a</template>
											<template v-else>Paste a</template>
											<open-in-browser url="https://github.com/settings/tokens" text="personal access token" class="text-primary"></open-in-browser>
											with the <code>public_repo</code> scope.
										</p>
										<div class="d-flex align-center ga-2">
											<v-text-field v-model="patToken" :type="showToken ? 'text' : 'password'"
												label="Personal access token" density="compact" hide-details
												:append-inner-icon="showToken ? 'fas fa-eye-slash' : 'fas fa-eye'"
												@click:append-inner="showToken = !showToken"></v-text-field>
											<v-btn color="primary" variant="flat" :disabled="!patToken" @click="signInWithToken">Sign in</v-btn>
										</div>
									</div>
								</template>

								<v-alert v-if="!auth.encryptionAvailable" type="warning" variant="tonal" density="compact" class="mt-3">
									This system has no secure credential store available, so the token would be saved unencrypted
									in the editor's settings file. Consider using a short-lived token.
								</v-alert>
							</div>
						</v-card-text>
					</v-card>

					<p class="text-medium-emphasis text-caption mb-2">
						<template v-if="hasDefaultDataset">
							Showing tables and records you've added or changed from the defaults.
							<a href="#" class="text-primary" @click.prevent="picker.onlyChanged = !picker.onlyChanged">
								{{ picker.onlyChanged ? 'Browse everything instead' : 'Show only what changed' }}
							</a>
						</template>
						<template v-else>
							Showing every table and record. No default dataset is loaded for this project, so
							changes cannot be detected.
						</template>
					</p>

					<p v-if="picker.onlyChanged && hasDefaultDataset && visibleTables.length === 0"
						class="text-medium-emphasis text-caption mb-3">
						No tables have records that differ from the defaults yet.
						<a href="#" class="text-primary" @click.prevent="picker.onlyChanged = false">Browse everything instead</a>.
					</p>

					<div v-else class="d-flex align-center ga-2 mb-1">
						<v-select v-model="picker.table" :items="tableItems" item-title="displayLabel" item-value="key"
							label="Database table" density="compact" hide-details style="max-width: 260px"></v-select>

						<v-autocomplete v-model="picker.recordIds" :items="availableRecords" item-title="name" item-value="id"
							label="Records" density="compact" hide-details multiple chips closable-chips
							:disabled="picker.table === null">
							<template #chip="{ item, props: chipProps }">
								<v-chip v-bind="chipProps">
									<v-icon v-if="item.raw.operation" size="x-small" class="mr-1"
										:class="`text-${operationColor(item.raw.operation)}`">fas fa-circle</v-icon>
									{{ item.raw.name }}
								</v-chip>
							</template>
							<template #item="{ item, props: itemProps }">
								<v-list-item v-bind="itemProps" :title="item.raw.name">
									<template v-if="item.raw.operation" #append>
										<v-chip size="x-small" :color="operationColor(item.raw.operation)" variant="flat">
											{{ operationLabel(item.raw.operation) }}
										</v-chip>
									</template>
								</v-list-item>
							</template>
						</v-autocomplete>

						<v-btn color="primary" variant="flat" :disabled="!canStage" @click="stageSelected">Add</v-btn>
					</div>

					<p v-if="picker.table !== null && recordsAreFiltered && !page.loading && availableRecords.length === 0"
						class="text-medium-emphasis text-caption mb-3">
						No added or changed records found in this table.
						<a href="#" class="text-primary" @click.prevent="picker.onlyChanged = false">Browse everything instead</a>.
					</p>

					<v-table v-if="staged.length > 0" density="compact" class="mb-3 border rounded">
						<thead>
							<tr>
								<th>Record</th>
								<th>Table</th>
								<th>File</th>
								<th class="text-right">Remove</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="record in staged" :key="`${record.table}-${record.id}`">
								<td>{{ record.name }}</td>
								<td class="text-medium-emphasis">{{ record.tableLabel }}</td>
								<td class="text-medium-emphasis"><code>{{ record.fileName }}</code></td>
								<td class="text-right">
									<v-btn icon="fas fa-xmark" variant="text" size="x-small" @click="unstage(record)"></v-btn>
								</td>
							</tr>
						</tbody>
					</v-table>
					<p v-else class="text-medium-emphasis mb-3">
						No records added yet. Choose a table, pick one or more records, then select Add.
					</p>

					<v-expansion-panels v-if="unsupported.length > 0" variant="accordion" class="mb-3">
						<v-expansion-panel title="Why aren't all tables listed?">
							<v-expansion-panel-text>
								<div v-for="item in unsupported" :key="item.file_name" class="mb-3">
									<strong>{{ item.file_name }}</strong>
									<p class="text-medium-emphasis mb-0">{{ item.reason }}</p>
								</div>
							</v-expansion-panel-text>
						</v-expansion-panel>
					</v-expansion-panels>
				</div>

				<!-- Step 2: review what each record would do, then describe the change -->
				<div v-else-if="step === 2 && plan !== null">
					<p class="text-medium-emphasis mb-3">
						{{ plan.summary.added }} to add, {{ plan.summary.updated }} to update<span
							v-if="plan.summary.unchanged"> ({{ plan.summary.unchanged }} already up to date, so left out)</span>.
					</p>

					<v-alert v-for="error in plan.errors" :key="error" type="error" variant="tonal" density="compact" class="mb-2">
						{{ error }}
					</v-alert>

					<v-expansion-panels variant="accordion" class="mb-4">
						<v-expansion-panel v-for="item in plan.items" :key="`${item.table}-${item.record_id}`">
							<v-expansion-panel-title>
								<div class="d-flex align-center ga-3">
									<v-chip size="x-small" :color="operationColor(item.operation)" variant="flat">
										{{ operationLabel(item.operation) }}
									</v-chip>
									<span>{{ item.record_name }}</span>
									<span class="text-medium-emphasis text-caption"><code>{{ item.file_name }}</code></span>
									<v-icon v-if="item.errors.length > 0" size="small" class="text-error">fas fa-circle-exclamation</v-icon>
								</div>
							</v-expansion-panel-title>
							<v-expansion-panel-text>
								<div class="overflow-x-auto border rounded pa-3 mb-3 bg-surface-light">
									<pre class="text-caption mb-0"><code>{{ item.header_line }}
<template v-if="item.existing_row_line">- {{ item.existing_row_line }}
+ </template>{{ item.row_line }}</code></pre>
								</div>

								<v-alert v-for="error in item.errors" :key="error" type="error" variant="tonal" density="compact" class="mb-2">
									{{ error }}
								</v-alert>
								<v-alert v-for="warning in item.warnings" :key="warning" type="warning" variant="tonal" density="compact" class="mb-2">
									{{ warning }}
								</v-alert>
							</v-expansion-panel-text>
						</v-expansion-panel>
					</v-expansion-panels>

					<v-alert v-if="plan.valid" type="success" variant="tonal" density="compact" class="mb-4">
						These records pass the reference database's checks. They will be proposed as
						{{ pullRequestCount }} separate pull request<span v-if="pullRequestCount !== 1">s</span>, one per file:
						<ul class="mt-1 mb-0">
							<li v-for="file in plan.files" :key="file.file_name">
								<strong>{{ plan.file_titles[file.file_name] }}</strong>
							</li>
						</ul>
					</v-alert>

					<p class="text-medium-emphasis mb-3">
						Everything below is optional, but it helps whoever reviews the change.
					</p>

					<v-textarea v-model="details.reason" label="Reason for the change" rows="2" density="compact" class="mb-3"></v-textarea>
					<v-textarea v-model="details.source" label="Source (publication, dataset, documentation, or expert)" rows="2" density="compact" class="mb-3"></v-textarea>
					<v-textarea v-model="details.notes" label="Notes" rows="2" density="compact"></v-textarea>
				</div>

				<!-- Step 3: one outcome per file, since each was its own pull request -->
				<div v-else-if="step === 3 && results.length > 0">
					<v-alert v-if="results.every(r => r.ok)" type="success" variant="tonal" class="mb-4">
						{{ results.length }} pull request<span v-if="results.length !== 1">s</span> opened on the reference database.
					</v-alert>
					<v-alert v-else-if="results.some(r => r.ok)" type="warning" variant="tonal" class="mb-4">
						{{ results.filter(r => r.ok).length }} of {{ results.length }} pull requests opened.
						See below for what failed.
					</v-alert>
					<v-alert v-else type="error" variant="tonal" class="mb-4">
						None of the pull requests could be opened.
					</v-alert>

					<v-list density="compact" class="mb-3 border rounded">
						<v-list-item v-for="outcome in results" :key="outcome.fileName">
							<template #prepend>
								<v-icon :class="outcome.ok ? 'text-success' : 'text-error'">
									{{ outcome.ok ? 'fas fa-circle-check' : 'fas fa-circle-exclamation' }}
								</v-icon>
							</template>
							<v-list-item-title><code>{{ outcome.fileName }}</code></v-list-item-title>
							<v-list-item-subtitle v-if="outcome.ok && outcome.data">
								<open-in-browser :url="outcome.data.url" :text="`Pull request #${outcome.data.number}`" class="text-primary"></open-in-browser>
								<span v-if="outcome.data.usedFork" class="text-caption"> (via your fork)</span>
							</v-list-item-subtitle>
							<v-list-item-subtitle v-else class="text-error">{{ outcome.error }}</v-list-item-subtitle>
						</v-list-item>
					</v-list>

					<p v-if="results.some(r => r.ok && r.data && r.data.usedFork)" class="text-medium-emphasis text-caption mb-0">
						Pull requests marked "via your fork" were pushed there because you don't have write access to the
						reference database directly. That is the normal path for a contribution.
					</p>
				</div>
			</v-card-text>

			<v-divider></v-divider>

			<v-card-actions>
				<v-btn v-if="step === 2" variant="text" @click="step = 1">Back</v-btn>
				<p v-if="page.submitting && submitProgress" class="text-caption text-medium-emphasis mb-0 mx-2">{{ submitProgress }}</p>
				<v-spacer></v-spacer>
				<v-btn variant="text" @click="close">{{ step === 3 ? 'Close' : 'Cancel' }}</v-btn>
				<v-btn v-if="step === 1" color="primary" variant="flat"
					:disabled="!canReview" :loading="page.loading" @click="buildPlan">
					Review {{ staged.length }} Record<span v-if="staged.length !== 1">s</span>
				</v-btn>
				<v-btn v-else-if="step === 2" color="primary" variant="flat"
					:disabled="!canSubmit" :loading="page.submitting" @click="submit">
					Open {{ pullRequestCount }} Pull Request<span v-if="pullRequestCount !== 1">s</span>
				</v-btn>
			</v-card-actions>
		</v-card>
	</v-dialog>
</template>
