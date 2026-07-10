import { getInjectedWallet } from "./wallet";

function b64decode(value: string) {
  return JSON.parse(atob(value));
}

function b64encode(value: unknown) {
  return btoa(JSON.stringify(value));
}

function randomNonceHex() {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return `0x${Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

export async function payX402Resource(resourceUrl: string, account: string) {
  const provider = getInjectedWallet();
  if (!provider) throw new Error("No EVM wallet provider found.");

  const challengeResp = await fetch(resourceUrl);
  if (challengeResp.status !== 402) {
    throw new Error(`Expected x402 challenge, got ${challengeResp.status}.`);
  }
  const requiredHeader = challengeResp.headers.get("PAYMENT-REQUIRED") || challengeResp.headers.get("payment-required");
  if (!requiredHeader) throw new Error("Arc Gateway did not return PAYMENT-REQUIRED header.");

  const challenge = b64decode(requiredHeader);
  const accepted = challenge.accepts[0];
  const chainId = parseInt(String(accepted.network).split(":")[1], 10);
  const now = Math.floor(Date.now() / 1000);
  const validBefore = String(now + Math.max(accepted.maxTimeoutSeconds || 0, 7 * 24 * 3600 + 600));
  const validAfter = String(now - 600);
  const nonce = randomNonceHex();

  const typedData = {
    types: {
      EIP712Domain: [
        { name: "name", type: "string" },
        { name: "version", type: "string" },
        { name: "chainId", type: "uint256" },
        { name: "verifyingContract", type: "address" },
      ],
      TransferWithAuthorization: [
        { name: "from", type: "address" },
        { name: "to", type: "address" },
        { name: "value", type: "uint256" },
        { name: "validAfter", type: "uint256" },
        { name: "validBefore", type: "uint256" },
        { name: "nonce", type: "bytes32" },
      ],
    },
    primaryType: "TransferWithAuthorization",
    domain: {
      name: "GatewayWalletBatched",
      version: "1",
      chainId,
      verifyingContract: accepted.extra.verifyingContract,
    },
    message: {
      from: account,
      to: accepted.payTo,
      value: accepted.amount,
      validAfter,
      validBefore,
      nonce,
    },
  };

  const signature = await provider.request<string>({
    method: "eth_signTypedData_v4",
    params: [account, JSON.stringify(typedData)],
  });

  const paymentPayload = {
    x402Version: 2,
    payload: {
      signature,
      authorization: typedData.message,
    },
    accepted,
    resource: challenge.resource,
  };

  const paidResp = await fetch(resourceUrl, {
    headers: { "payment-signature": b64encode(paymentPayload) },
  });
  const paidData = await paidResp.json().catch(async () => ({ error: await paidResp.text() }));
  if (!paidResp.ok) {
    throw new Error(String(paidData.reason || paidData.errorReason || paidData.message || paidData.error || "Arc settlement failed"));
  }
  return paidData;
}
