import React, { useEffect, useState } from "react";
import { getClientConfig } from "../../services/api";
import { NETWORK_MODE as STATIC_MODE, syncNetworkWithBackend } from "../../config/network";
import "./NetworkBadge.css";

export function NetworkBadge() {
  const [networkName, setNetworkName] = useState<string>(
    STATIC_MODE === "testnet" ? "Arc Testnet" : "Arc Mainnet"
  );
  const [isTestnet, setIsTestnet] = useState<boolean>(STATIC_MODE === "testnet");
  const [chainId, setChainId] = useState<number>(STATIC_MODE === "testnet" ? 5042002 : 5042);

  useEffect(() => {
    let mounted = true;
    getClientConfig()
      .then((cfg) => {
        if (!mounted || !cfg) return;
        const testnet = Boolean(
          (cfg.payment_network && (cfg.payment_network.includes("testnet") || cfg.payment_network.includes("5042002"))) ||
          (cfg.payment_network_name && cfg.payment_network_name.toLowerCase().includes("testnet"))
        );
        const netName = cfg.payment_network_name || (testnet ? "Arc Testnet" : "Arc Mainnet");
        syncNetworkWithBackend(testnet ? "arc-testnet" : "arc-mainnet");
        setNetworkName(netName);
        setIsTestnet(testnet);
        setChainId(testnet ? 5042002 : 5042);
      })
      .catch(() => {
        // Fallback to static mode if backend is booting or unreachable
      });
    return () => {
      mounted = false;
    };
  }, []);

  const tooltip = isTestnet
    ? `Live Network: Arc Testnet (Chain ID: ${chainId}) | Local DB: qma`
    : `Live Network: Arc Mainnet (Chain ID: ${chainId}) | Local DB: qma_mainnet`;

  return (
    <div
      className={`qma-network-badge ${isTestnet ? "is-testnet" : "is-mainnet"}`}
      title={tooltip}
      aria-label={tooltip}
    >
      <span className="qma-network-dot" aria-hidden="true" />
      <span className="qma-network-label">{networkName}</span>
    </div>
  );
}
