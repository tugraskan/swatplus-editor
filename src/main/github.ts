/**
 * GitHub authentication and pull-request submission for contributing records
 * to the SWAT+ authoritative reference database.
 *
 * This all lives in the main process on purpose: the access token is written
 * to disk encrypted with Electron's safeStorage and is never handed to the
 * renderer. The renderer asks for an auth status or a submission and gets back
 * a result, never a credential.
 *
 * Two ways to sign in are supported:
 *   - Device flow, when an OAuth app client id is configured in
 *     appsettings.json. This is the friendlier path: the user gets a short
 *     code to enter in their browser and never handles a token.
 *   - A personal access token the user pastes in. This needs no OAuth app
 *     registration, so it works in a stock build.
 */

import { safeStorage } from 'electron';
import Store from 'electron-store';

const API_ROOT = 'https://api.github.com';
const TOKEN_KEY = 'referenceDbGithubToken';
const TOKEN_PLAINTEXT_KEY = 'referenceDbGithubTokenIsPlaintext';
const METHOD_KEY = 'referenceDbGithubAuthMethod';

export interface ReferenceDbConfig {
	owner: string;
	repo: string;
	branch: string;
	oauthClientId: string;
}

export const DEFAULT_CONFIG: ReferenceDbConfig = {
	owner: 'tugraskan',
	repo: 'SWATPLUS-Authoritative-Reference-Database',
	branch: 'main',
	oauthClientId: ''
};

export interface SubmissionRequest {
	filePath: string;
	fileContents: string;
	recordName: string;
	tableLabel: string;
	/** Blob sha the submitted contents were built from, so a change made
	 *  upstream in the meantime is caught instead of being overwritten. */
	baseFileSha?: string;
	reason?: string;
	source?: string;
	notes?: string;
	editorVersion?: string;
}

function delay(ms: number) {
	return new Promise(resolve => setTimeout(resolve, ms));
}

export class GitHubClient {
	private store: Store;
	private config: ReferenceDbConfig;

	constructor(store: Store, config?: Partial<ReferenceDbConfig>) {
		this.store = store;
		this.config = Object.assign({}, DEFAULT_CONFIG, config || {});
	}

	getConfig(): ReferenceDbConfig {
		return this.config;
	}

	/* ---------------------------------------------------------------- token */

	private saveToken(token: string, method: string) {
		if (safeStorage.isEncryptionAvailable()) {
			this.store.set(TOKEN_KEY, safeStorage.encryptString(token).toString('base64'));
			this.store.set(TOKEN_PLAINTEXT_KEY, false);
		} else {
			// No OS keyring (common on a bare Linux desktop). Storing the token
			// unencrypted is the only way to offer "stay signed in" here, so it
			// is recorded as such and surfaced to the user rather than done
			// quietly.
			this.store.set(TOKEN_KEY, token);
			this.store.set(TOKEN_PLAINTEXT_KEY, true);
		}
		this.store.set(METHOD_KEY, method);
	}

	private readToken(): string | null {
		const stored = this.store.get(TOKEN_KEY) as string | undefined;
		if (!stored) return null;

		if (this.store.get(TOKEN_PLAINTEXT_KEY) === true) return stored;

		try {
			return safeStorage.decryptString(Buffer.from(stored, 'base64'));
		} catch {
			// Encrypted with a key we no longer have (different machine or OS
			// user). Drop it so the user is asked to sign in again.
			this.signOut();
			return null;
		}
	}

	signOut() {
		this.store.delete(TOKEN_KEY);
		this.store.delete(TOKEN_PLAINTEXT_KEY);
		this.store.delete(METHOD_KEY);
	}

	isTokenStoredInPlaintext(): boolean {
		return this.store.get(TOKEN_PLAINTEXT_KEY) === true;
	}

	/* ------------------------------------------------------------ transport */

	private async request(method: string, path: string, body?: any, token?: string) {
		const authToken = token !== undefined ? token : this.readToken();
		const headers: Record<string, string> = {
			'Accept': 'application/vnd.github+json',
			'X-GitHub-Api-Version': '2022-11-28',
			'User-Agent': 'SWATPlusEditor'
		};
		if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
		if (body !== undefined) headers['Content-Type'] = 'application/json';

		const url = path.startsWith('http') ? path : `${API_ROOT}${path}`;
		const response = await fetch(url, {
			method,
			headers,
			body: body === undefined ? undefined : JSON.stringify(body)
		});

		const text = await response.text();
		let parsed: any = null;
		if (text) {
			try { parsed = JSON.parse(text); } catch { parsed = text; }
		}

		if (!response.ok) {
			const message = parsed && parsed.message ? parsed.message : `${response.status} ${response.statusText}`;
			const error: any = new Error(message);
			error.status = response.status;
			error.body = parsed;
			throw error;
		}

		return parsed;
	}

	/* ----------------------------------------------------------------- auth */

	async getAuthStatus() {
		const token = this.readToken();
		if (!token) {
			return {
				authenticated: false,
				deviceFlowAvailable: !!this.config.oauthClientId,
				encryptionAvailable: safeStorage.isEncryptionAvailable()
			};
		}

		try {
			const user = await this.request('GET', '/user', undefined, token);
			return {
				authenticated: true,
				login: user.login,
				method: this.store.get(METHOD_KEY) || 'token',
				tokenInPlaintext: this.isTokenStoredInPlaintext(),
				deviceFlowAvailable: !!this.config.oauthClientId,
				encryptionAvailable: safeStorage.isEncryptionAvailable()
			};
		} catch {
			// Token revoked or expired.
			this.signOut();
			return {
				authenticated: false,
				deviceFlowAvailable: !!this.config.oauthClientId,
				encryptionAvailable: safeStorage.isEncryptionAvailable()
			};
		}
	}

	/** Validate and store a personal access token. */
	async signInWithToken(token: string) {
		const trimmed = (token || '').trim();
		if (!trimmed) throw new Error('Enter a personal access token.');

		const user = await this.request('GET', '/user', undefined, trimmed);
		this.saveToken(trimmed, 'token');
		return { login: user.login, tokenInPlaintext: this.isTokenStoredInPlaintext() };
	}

	/** Step one of the device flow: ask GitHub for a user code. */
	async startDeviceFlow() {
		if (!this.config.oauthClientId) {
			throw new Error('No GitHub OAuth app is configured for this build, so browser sign-in is unavailable. Use a personal access token instead.');
		}

		const response = await fetch('https://github.com/login/device/code', {
			method: 'POST',
			headers: { 'Accept': 'application/json', 'Content-Type': 'application/json', 'User-Agent': 'SWATPlusEditor' },
			body: JSON.stringify({ client_id: this.config.oauthClientId, scope: 'public_repo' })
		});
		const data: any = await response.json();
		if (data.error) throw new Error(data.error_description || data.error);

		return {
			deviceCode: data.device_code,
			userCode: data.user_code,
			verificationUri: data.verification_uri,
			interval: data.interval || 5,
			expiresIn: data.expires_in || 900
		};
	}

	/**
	 * Step two: poll until the user approves in the browser. Resolves with the
	 * signed-in login, or throws if they deny or the code expires.
	 */
	async pollDeviceFlow(deviceCode: string, intervalSeconds: number, expiresInSeconds: number) {
		let interval = (intervalSeconds || 5) * 1000;
		const deadline = Date.now() + (expiresInSeconds || 900) * 1000;

		while (Date.now() < deadline) {
			await delay(interval);

			const response = await fetch('https://github.com/login/oauth/access_token', {
				method: 'POST',
				headers: { 'Accept': 'application/json', 'Content-Type': 'application/json', 'User-Agent': 'SWATPlusEditor' },
				body: JSON.stringify({
					client_id: this.config.oauthClientId,
					device_code: deviceCode,
					grant_type: 'urn:ietf:params:oauth:grant-type:device_code'
				})
			});
			const data: any = await response.json();

			if (data.access_token) {
				this.saveToken(data.access_token, 'device');
				const user = await this.request('GET', '/user', undefined, data.access_token);
				return { login: user.login, tokenInPlaintext: this.isTokenStoredInPlaintext() };
			}

			if (data.error === 'authorization_pending') continue;
			if (data.error === 'slow_down') {
				interval += 5000;
				continue;
			}
			throw new Error(data.error_description || data.error || 'Sign-in failed.');
		}

		throw new Error('Sign-in timed out. Start again to get a new code.');
	}

	/* ----------------------------------------------------------- repo access */

	/** Current text of a file on the reference database's default branch. */
	async getFile(filePath: string) {
		const { owner, repo, branch } = this.config;
		const data = await this.request(
			'GET', `/repos/${owner}/${repo}/contents/${encodeURIComponent(filePath)}?ref=${encodeURIComponent(branch)}`);
		return {
			text: Buffer.from(data.content, 'base64').toString('utf8'),
			sha: data.sha
		};
	}

	/**
	 * Resolve where the branch should live. A user with push access to the
	 * reference database branches on it directly; everyone else gets a fork,
	 * created and brought up to date with upstream if needed.
	 */
	private async resolveHeadRepo(login: string) {
		const { owner, repo } = this.config;

		const upstream = await this.request('GET', `/repos/${owner}/${repo}`);
		if (upstream.permissions && upstream.permissions.push) {
			return { owner, repo, isFork: false };
		}

		try {
			await this.request('GET', `/repos/${login}/${repo}`);
		} catch (e: any) {
			if (e.status !== 404) throw e;
			await this.request('POST', `/repos/${owner}/${repo}/forks`);

			// Forking is asynchronous; wait for the repo to become readable.
			let ready = false;
			for (let attempt = 0; attempt < 15 && !ready; attempt++) {
				await delay(2000);
				try {
					await this.request('GET', `/repos/${login}/${repo}`);
					ready = true;
				} catch (pollError: any) {
					if (pollError.status !== 404) throw pollError;
				}
			}
			if (!ready) throw new Error('Timed out waiting for your fork of the reference database to be created.');
		}

		// An existing fork may be behind upstream. Failing to sync is not fatal
		// -- it only matters if the target file changed -- so it is not fatal
		// here either.
		try {
			await this.request('POST', `/repos/${login}/${repo}/merge-upstream`, { branch: this.config.branch });
		} catch { /* fork may already be current, or have diverged */ }

		return { owner: login, repo, isFork: true };
	}

	private buildPullRequestBody(request: SubmissionRequest) {
		const blank = '_Not provided._';
		return [
			'## Reason',
			'',
			request.reason && request.reason.trim() ? request.reason.trim() : blank,
			'',
			'## Source',
			'',
			request.source && request.source.trim() ? request.source.trim() : blank,
			'',
			'## Notes',
			'',
			request.notes && request.notes.trim() ? request.notes.trim() : blank,
			'',
			'---',
			'',
			`Submitted from SWAT+ Editor${request.editorVersion ? ` ${request.editorVersion}` : ''}.`,
			`Adds the \`${request.recordName}\` record to \`${request.filePath}\`.`
		].join('\n');
	}

	/** Create the branch, commit the one-line change, and open the pull request. */
	async submitRecord(request: SubmissionRequest) {
		const token = this.readToken();
		if (!token) throw new Error('Sign in to GitHub before submitting.');

		const { owner, repo, branch } = this.config;
		const user = await this.request('GET', '/user');
		const head = await this.resolveHeadRepo(user.login);

		const baseRef = await this.request('GET', `/repos/${owner}/${repo}/git/ref/heads/${branch}`);
		const baseSha = baseRef.object.sha;

		const safeName = request.recordName.replace(/[^a-zA-Z0-9._-]/g, '-').toLowerCase();
		const branchName = `add-${safeName}-${Date.now().toString(36)}`;

		await this.request('POST', `/repos/${head.owner}/${head.repo}/git/refs`, {
			ref: `refs/heads/${branchName}`,
			sha: baseSha
		});

		// The blob sha must come from the head repo on the new branch, which is
		// where the update is being written.
		const current = await this.request(
			'GET', `/repos/${head.owner}/${head.repo}/contents/${encodeURIComponent(request.filePath)}?ref=${encodeURIComponent(branchName)}`);

		// The submitted contents were assembled from the file as it looked when
		// the record was reviewed. If it has moved since, the assembled text no
		// longer contains whatever changed, and committing it would quietly
		// revert that change.
		if (request.baseFileSha && current.sha !== request.baseFileSha) {
			throw new Error(
				`${request.filePath} changed in the reference database while you were reviewing this record. ` +
				'Go back and review it again so your submission is based on the current file.');
		}

		await this.request('PUT', `/repos/${head.owner}/${head.repo}/contents/${encodeURIComponent(request.filePath)}`, {
			message: `Add ${request.recordName} to ${request.filePath}`,
			content: Buffer.from(request.fileContents, 'utf8').toString('base64'),
			sha: current.sha,
			branch: branchName
		});

		const pullRequest = await this.request('POST', `/repos/${owner}/${repo}/pulls`, {
			title: `Add ${request.recordName} to ${request.filePath}`,
			head: head.isFork ? `${user.login}:${branchName}` : branchName,
			base: branch,
			body: this.buildPullRequestBody(request),
			maintainer_can_modify: true
		});

		return {
			url: pullRequest.html_url,
			number: pullRequest.number,
			branch: branchName,
			usedFork: head.isFork
		};
	}
}
