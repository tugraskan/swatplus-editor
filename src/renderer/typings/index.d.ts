export interface ElectronGlobals {
	dev_mode: boolean;
	platform: string|null;
	project_db: string|null;
	api_port: number|null;
	locale: string|null;
	swat_path: string|null;
}

export interface ElectronAppSettings {
	version: string;
	swatplus: string;
	python: boolean;
	pythonPath: string;
	referenceDb?: {
		owner: string;
		repo: string;
		branch: string;
		oauthClientId: string;
	};
}

export interface ReferenceDbConfig {
	owner: string;
	repo: string;
	branch: string;
}

/** Main-process calls report failure in the payload rather than throwing across IPC. */
export interface ReferenceDbResult<T> {
	ok: boolean;
	data?: T;
	error?: string;
}

export interface ReferenceDbAuthStatus {
	authenticated: boolean;
	login?: string;
	method?: string;
	tokenInPlaintext?: boolean;
	deviceFlowAvailable: boolean;
	encryptionAvailable: boolean;
}

export interface ReferenceDbDeviceCode {
	deviceCode: string;
	userCode: string;
	verificationUri: string;
	interval: number;
	expiresIn: number;
}

export interface ReferenceDbSubmission {
	filePath: string;
	fileContents: string;
	recordName: string;
	tableLabel: string;
	baseFileSha?: string;
	reason?: string;
	source?: string;
	notes?: string;
	editorVersion?: string;
}

export interface ReferenceDbPullRequest {
	url: string;
	number: number;
	branch: string;
	usedFork: boolean;
}

export interface ReferenceDbTable {
	key: string;
	label: string;
	file_name: string;
	docs_path: string;
}

export interface ReferenceDbPreview {
	table: string;
	label: string;
	file_name: string;
	record_id: number;
	record_name: string;
	meta_line: string;
	header_line: string;
	row_line: string;
	columns: string[];
	errors: string[];
	warnings: string[];
	valid: boolean;
	file_contents?: string;
}

export interface ProjectSettings {
	projectDb: string|null;
	datasetsDb: string|null;
	name: string|null;
	description: string|null;
	version: string|null;
	isLte: boolean;
	swatVersion: string|null;
}

export interface GridViewHeader {
	key: string;
	label?: string|null;
	noSort?: boolean|null;
	class?: string|null;
	type?: 'string'|'int'|'number'|'boolean'|'object'|'file'|'variable-object'|null;
	decimals?: number|null;
	objectValueField?: string|null;
	objectTextField?: string|null;
	objectRoutePath?: string|null;
	ignoreObjectRouteId?: boolean|null;
	filePath?: string|null;
	defaultIfNull?: string|null;
	formatter?: (value:any) => string;
}