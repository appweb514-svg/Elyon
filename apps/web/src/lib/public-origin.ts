/** Origine publique derrière Tailscale / reverse-proxy (évite localhost). */

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]);

function hostName(hostHeader: string): string {
  if (hostHeader.startsWith("[")) {
    const end = hostHeader.indexOf("]");
    return end >= 0 ? hostHeader.slice(1, end) : hostHeader;
  }
  return hostHeader.split(":")[0] ?? hostHeader;
}

export function publicOrigin(input: {
  requestOrigin: string;
  envUrl?: string;
  forwardedHost?: string | null;
  forwardedProto?: string | null;
  host?: string | null;
}): string {
  const env = (input.envUrl ?? "").trim().replace(/\/$/, "");
  if (env) {
    return env;
  }
  const forwardedHost = (input.forwardedHost ?? "").trim();
  if (forwardedHost && !LOCAL_HOSTS.has(hostName(forwardedHost))) {
    const proto = (input.forwardedProto ?? "https").replace(/:$/, "");
    return `${proto}://${forwardedHost}`;
  }
  const host = (input.host ?? "").trim();
  if (host && !LOCAL_HOSTS.has(hostName(host))) {
    const proto = (input.forwardedProto ?? "https").replace(/:$/, "");
    return `${proto}://${host}`;
  }
  return input.requestOrigin.replace(/\/$/, "");
}
