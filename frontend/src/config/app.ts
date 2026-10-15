/**
 * Shared Business & Client Configuration
 *
 * Sourced directly from the single source of truth: `config/app.json`.
 */

import appData from "../../../config/app.json";

export const appConfig = appData;

export const PUBLIC_API_URL = appData.deployments.publicApiUrl;
export const PUBLIC_APP_URL = appData.deployments.publicAppUrl;
export const PUBLIC_MCP_URL = appData.deployments.publicMcpUrl;
export const PUBLIC_DOCS_URL = appData.deployments.publicDocsUrl;
