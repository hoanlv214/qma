import { ApiReferenceReact } from "@scalar/api-reference-react";
import "@scalar/api-reference-react/style.css";
import { API_BASE_URL } from "../../services/api";

export function DocsPage() {
  const parts = window.location.pathname.split("/");
  const audience = parts.length > 2 && parts[2] ? parts[2] : "";

  const openApiUrl = audience ? `${API_BASE_URL}/openapi/${audience}.json` : `${API_BASE_URL}/openapi.json`;

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '10px 20px', background: '#1e1e1e', color: 'white', display: 'flex', gap: '20px', alignItems: 'center', borderBottom: '1px solid #333' }}>
        <strong style={{ fontSize: '1.1rem' }}>QMA API Docs:</strong>
        <a href="/docs/agent" style={{ color: audience === 'agent' ? '#4ade80' : '#ccc', textDecoration: 'none', fontWeight: audience === 'agent' ? 'bold' : 'normal' }}>Agent</a>
        <a href="/docs/wallet" style={{ color: audience === 'wallet' ? '#4ade80' : '#ccc', textDecoration: 'none', fontWeight: audience === 'wallet' ? 'bold' : 'normal' }}>Wallet</a>
        <a href="/docs/admin" style={{ color: audience === 'admin' ? '#4ade80' : '#ccc', textDecoration: 'none', fontWeight: audience === 'admin' ? 'bold' : 'normal' }}>Admin</a>
        <a href="/docs" style={{ color: !audience ? '#4ade80' : '#ccc', textDecoration: 'none', fontWeight: !audience ? 'bold' : 'normal' }}>Full</a>
      </div>
      <div style={{ flex: 1, overflow: 'auto' }}>
        <ApiReferenceReact configuration={{ url: openApiUrl }} />
      </div>
    </div>
  );
}
