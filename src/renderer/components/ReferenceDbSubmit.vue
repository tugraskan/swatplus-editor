<script setup lang="ts">
	/**
	 * Propose one of the current project's database records for inclusion in
	 * the SWAT+ authoritative reference database, as a pull request.
	 *
	 * The row is formatted by the editor's own file writers (via the API), so
	 * the pull request is a single added line in the same format the reference
	 * database already stores. Authentication and the GitHub calls happen in
	 * the main process; no token is handled here.
	 */
	import { computed, reactive, ref, watch } from 'vue';
	import { useHelpers } from '@/helpers';
	import type { ReferenceDbPreview, ReferenceDbTable } from '@/typings';

	const { api, constants, currentProject, errors, utilities } = useHelpers();
	const electron = window.electronApi;

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
	const records = ref<{ id: number, name: string }[]>([]);

	const selection = reactive({
		table: null as string | null,
		recordId: null as number | null,
		reason: '',
		source: '',
		notes: ''
	});

	const preview = ref<ReferenceDbPreview | null>(null);
	/** Blob sha the preview was built from, carried into the submission so an
	 *  upstream change made in between is caught rather than overwritten. */
	const previewFileSha = ref('');
	const result = ref<{ url: string, number: number, usedFork: boolean } | null>(null);

	const selectedTable = computed(() => tables.value.find(t => t.key === selection.table) || null);
	const canPreview = computed(() => selection.table !== null && selection.recordId !== null);
	const canSubmit = computed(() =>
		auth.authenticated && preview.value !== null && preview.value.valid && !page.submitting);

	async function open() {
		show.value = true;
		step.value = 1;
		result.value = null;
		preview.value = null;
		page.error = null;

		const config = await electron.referenceDbConfig();
		Object.assign(repo, config);

		await Promise.all([loadTables(), checkAuth()]);
	}

	async function loadTables() {
		page.loading = true;
		try {
			const response = await api.get('reference-db/tables', currentProject.getApiHeader());
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
			auth.login = response.data.login ?? '';
			auth.deviceFlowAvailable = response.data.deviceFlowAvailable;
			auth.encryptionAvailable = response.data.encryptionAvailable;
			auth.tokenInPlaintext = response.data.tokenInPlaintext ?? false;
		} else {
			auth.error = response.error ?? 'Unable to check GitHub sign-in status.';
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
			auth.error = response.error ?? 'Sign-in failed.';
		}
		auth.checking = false;
	}

	async function startDeviceFlow() {
		auth.error = null;
		const started = await electron.referenceDbDeviceStart();
		if (!started.ok || !started.data) {
			auth.error = started.error ?? 'Unable to start GitHub sign-in.';
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
			auth.error = finished.error ?? 'Sign-in failed.';
		}
	}

	async function signOut() {
		await electron.referenceDbSignOut();
		auth.authenticated = false;
		auth.login = '';
	}

	async function loadRecords() {
		records.value = [];
		selection.recordId = null;
		preview.value = null;
		if (selection.table === null) return;

		page.loading = true;
		try {
			const response = await api.get(`reference-db/records/${selection.table}`, currentProject.getApiHeader());
			records.value = response.data.records;
		} catch (error) {
			page.error = errors.logError(error, 'Unable to load records for this table.');
		}
		page.loading = false;
	}

	/**
	 * Fetch the file as it currently stands upstream, then have the API format
	 * the row and check it against that file. Doing it in this order is what
	 * lets duplicate names and column drift be caught before anything is
	 * pushed to GitHub.
	 */
	async function buildPreview() {
		if (!canPreview.value || selectedTable.value === null) return;

		page.loading = true;
		page.error = null;
		preview.value = null;

		const filePath = `database_files/${selectedTable.value.file_name}`;
		const file = await electron.referenceDbGetFile(filePath);
		if (!file.ok || !file.data) {
			page.error = file.error ?? 'Unable to read the current file from the reference database.';
			page.loading = false;
			return;
		}

		try {
			const response = await api.post('reference-db/preview', {
				table: selection.table,
				id: selection.recordId,
				existing_file_text: file.data.text
			}, currentProject.getApiHeader());
			preview.value = response.data;
			previewFileSha.value = file.data.sha;
			step.value = 2;
		} catch (error) {
			page.error = errors.logError(error, 'Unable to prepare this record for submission.');
		}
		page.loading = false;
	}

	async function submit() {
		if (!canSubmit.value || preview.value === null || selectedTable.value === null) return;

		page.submitting = true;
		page.error = null;

		const response = await electron.referenceDbSubmit({
			filePath: `database_files/${selectedTable.value.file_name}`,
			fileContents: preview.value.file_contents ?? '',
			recordName: preview.value.record_name,
			tableLabel: preview.value.label,
			baseFileSha: previewFileSha.value,
			reason: selection.reason,
			source: selection.source,
			notes: selection.notes,
			editorVersion: constants.appSettings.version
		});

		if (response.ok && response.data) {
			result.value = response.data;
			step.value = 3;
		} else {
			page.error = response.error ?? 'Unable to open the pull request.';
		}
		page.submitting = false;
	}

	function close() {
		show.value = false;
		device.active = false;
	}

	watch(() => selection.table, async () => await loadRecords());

	defineExpose({ open });
</script>

<template>
	<v-list-item @click="open" border="t" class="text-primary">
		<template #prepend><v-icon class="text-medium-emphasis">fas fa-code-pull-request</v-icon></template>
		Contribute a Record to the Reference Database
	</v-list-item>

	<v-dialog v-model="show" :max-width="constants.dialogSizes.lg" scrollable>
		<v-card>
			<v-card-title>Contribute a Record to the Reference Database</v-card-title>

			<v-card-text>
				<error-alert :text="page.error"></error-alert>

				<!-- Step 1: pick a record and sign in -->
				<div v-if="step === 1">
					<p class="text-medium-emphasis mb-4">
						Propose one of this project's database records for inclusion in the
						<open-in-browser :url="repoUrl" :text="`${repo.owner}/${repo.repo}`" class="text-primary"></open-in-browser>
						reference database. The editor formats the record exactly as that database stores it and opens a pull
						request adding a single line. A reviewer there decides whether to merge it.
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

					<v-select v-model="selection.table" :items="tables" item-title="label" item-value="key"
						label="Database table" density="compact" class="mb-3"></v-select>

					<v-autocomplete v-model="selection.recordId" :items="records" item-title="name" item-value="id"
						label="Record" density="compact" :disabled="selection.table === null"
						:hint="selection.table === null ? 'Choose a table first' : `${records.length} records in this project`"
						persistent-hint class="mb-3"></v-autocomplete>

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

				<!-- Step 2: review the formatted row and describe the change -->
				<div v-else-if="step === 2 && preview !== null">
					<p class="text-medium-emphasis mb-3">
						This is the exact line that will be added to
						<code>database_files/{{ preview.file_name }}</code>.
					</p>

					<div class="overflow-x-auto border rounded pa-3 mb-4 bg-surface-light">
						<pre class="text-caption mb-0"><code>{{ preview.header_line }}
{{ preview.row_line }}</code></pre>
					</div>

					<v-alert v-for="error in preview.errors" :key="error" type="error" variant="tonal" density="compact" class="mb-2">
						{{ error }}
					</v-alert>
					<v-alert v-for="warning in preview.warnings" :key="warning" type="warning" variant="tonal" density="compact" class="mb-2">
						{{ warning }}
					</v-alert>

					<v-alert v-if="preview.valid" type="success" variant="tonal" density="compact" class="mb-4">
						This record passes the reference database's checks.
					</v-alert>

					<p class="text-medium-emphasis mb-3">
						Everything below is optional, but it helps whoever reviews the change.
					</p>

					<v-textarea v-model="selection.reason" label="Reason for the change" rows="2" density="compact" class="mb-3"></v-textarea>
					<v-textarea v-model="selection.source" label="Source (publication, dataset, documentation, or expert)" rows="2" density="compact" class="mb-3"></v-textarea>
					<v-textarea v-model="selection.notes" label="Notes" rows="2" density="compact"></v-textarea>
				</div>

				<!-- Step 3: the pull request is open -->
				<div v-else-if="step === 3 && result !== null">
					<v-alert type="success" variant="tonal" class="mb-4">
						Pull request #{{ result.number }} is open on the reference database.
					</v-alert>
					<p class="mb-3">
						<open-in-browser :url="result.url" :text="result.url" class="text-primary"></open-in-browser>
					</p>
					<p v-if="result.usedFork" class="text-medium-emphasis mb-0">
						You do not have write access to the reference database, so the change was pushed to your own fork
						and proposed from there. That is the normal path for a contribution.
					</p>
				</div>
			</v-card-text>

			<v-divider></v-divider>

			<v-card-actions>
				<v-btn v-if="step === 2" variant="text" @click="step = 1">Back</v-btn>
				<v-spacer></v-spacer>
				<v-btn variant="text" @click="close">{{ step === 3 ? 'Close' : 'Cancel' }}</v-btn>
				<v-btn v-if="step === 1" color="primary" variant="flat"
					:disabled="!canPreview" :loading="page.loading" @click="buildPreview">
					Review Record
				</v-btn>
				<v-btn v-else-if="step === 2" color="primary" variant="flat"
					:disabled="!canSubmit" :loading="page.submitting" @click="submit">
					Open Pull Request
				</v-btn>
			</v-card-actions>
		</v-card>
	</v-dialog>
</template>
