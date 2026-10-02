import type { FirebaseUser } from "./cleanup.ts";

type ServiceAccount = { project_id?: string; client_email?: string; private_key?: string };
type FirebasePage = { users?: Array<{ localId?: string }>; nextPageToken?: string };

function base64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/gu, "-").replace(/\//gu, "_").replace(/=+$/gu, "");
}

function jsonBase64Url(value: object): string {
  return base64Url(new TextEncoder().encode(JSON.stringify(value)));
}

function privateKeyBytes(pem: string): Uint8Array {
  const body = pem.replace(/-----BEGIN PRIVATE KEY-----|-----END PRIVATE KEY-----|\s/gu, "");
  const binary = atob(body);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

export class FirebaseAuthClient {
  private readonly account: ServiceAccount;
  private readonly request: typeof fetch;
  private token?: { value: string; expiresAt: number };

  constructor(encodedCredentials: string, projectId: string, request: typeof fetch = fetch) {
    let parsed: ServiceAccount;
    try { parsed = JSON.parse(atob(encodedCredentials)) as ServiceAccount; }
    catch { throw new Error("invalid_firebase_credentials"); }
    if (parsed.project_id !== projectId || !parsed.client_email || !parsed.private_key) {
      throw new Error("firebase_project_or_credentials_mismatch");
    }
    this.account = parsed;
    this.request = request.bind(globalThis);
  }

  private async accessToken(): Promise<string> {
    if (this.token && this.token.expiresAt > Date.now() + 60_000) return this.token.value;
    const issued = Math.floor(Date.now() / 1000);
    const unsigned = `${jsonBase64Url({ alg: "RS256", typ: "JWT" })}.${jsonBase64Url({
      iss: this.account.client_email,
      scope: "https://www.googleapis.com/auth/identitytoolkit",
      aud: "https://oauth2.googleapis.com/token",
      iat: issued,
      exp: issued + 3600,
    })}`;
    let key: CryptoKey;
    try {
      key = await crypto.subtle.importKey(
        "pkcs8", privateKeyBytes(this.account.private_key!),
        { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["sign"],
      );
    } catch { throw new Error("firebase_key_import_failed"); }
    let signature: Uint8Array;
    try {
      signature = new Uint8Array(await crypto.subtle.sign(
        "RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(unsigned),
      ));
    } catch { throw new Error("firebase_jwt_sign_failed"); }
    const assertion = `${unsigned}.${base64Url(signature)}`;
    let response: Response;
    try {
      response = await this.request("https://oauth2.googleapis.com/token", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer", assertion,
        }).toString(),
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "";
      const reason = message === "Network connection lost." ? "network_connection_lost"
        : message === "fetch failed" ? "fetch_failed"
          : message === "Failed to fetch" ? "failed_to_fetch"
            : message.toLowerCase().includes("duplex") ? "duplex_required"
              : error instanceof TypeError ? "type_error" : "unknown";
      throw new Error(`firebase_oauth_${reason}`);
    }
    if (!response.ok) throw new Error("firebase_oauth_failed");
    const payload = await response.json() as { access_token?: string; expires_in?: number };
    if (!payload.access_token) throw new Error("firebase_oauth_failed");
    this.token = { value: payload.access_token, expiresAt: Date.now() + (payload.expires_in ?? 3600) * 1000 };
    return payload.access_token;
  }

  async *listUsers(projectId: string): AsyncIterable<FirebaseUser> {
    let pageToken: string | undefined;
    do {
      const url = new URL(`https://identitytoolkit.googleapis.com/v1/projects/${encodeURIComponent(projectId)}/accounts:batchGet`);
      url.searchParams.set("maxResults", "1000");
      if (pageToken) url.searchParams.set("nextPageToken", pageToken);
      let response: Response;
      try {
        response = await this.request(url, { headers: { Authorization: `Bearer ${await this.accessToken()}` } });
      } catch (error) {
        if (error instanceof Error && /^firebase_[a-z_]+$/u.test(error.message)) throw error;
        throw new Error("firebase_list_transport_failed");
      }
      if (!response.ok) throw new Error("firebase_list_users_failed");
      const page = await response.json() as FirebasePage;
      for (const user of page.users ?? []) {
        if (!user.localId) throw new Error("firebase_user_missing_uid");
        yield { uid: user.localId };
      }
      pageToken = page.nextPageToken || undefined;
    } while (pageToken);
  }

  async deleteUser(projectId: string, uid: string): Promise<void> {
    const response = await this.request("https://identitytoolkit.googleapis.com/v1/accounts:delete", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${await this.accessToken()}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ localId: uid, targetProjectId: projectId }),
    });
    if (!response.ok) throw new Error("firebase_delete_user_failed");
  }
}
