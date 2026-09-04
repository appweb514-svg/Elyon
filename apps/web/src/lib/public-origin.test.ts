import { describe, expect, it } from "vitest";
import { publicOrigin } from "./public-origin";

describe("publicOrigin", () => {
  it("préfère l'URL publique configurée", () => {
    expect(
      publicOrigin({
        requestOrigin: "http://localhost:5140",
        envUrl: "https://vps-901.tailda1dd3.ts.net:5140/",
        host: "localhost:5140",
      })
    ).toBe("https://vps-901.tailda1dd3.ts.net:5140");
  });

  it("utilise X-Forwarded-Host plutôt que localhost", () => {
    expect(
      publicOrigin({
        requestOrigin: "http://localhost:5140",
        forwardedHost: "vps-901.tailda1dd3.ts.net:5140",
        forwardedProto: "https",
        host: "localhost:5140",
      })
    ).toBe("https://vps-901.tailda1dd3.ts.net:5140");
  });

  it("garde localhost en local sans config", () => {
    expect(
      publicOrigin({
        requestOrigin: "http://localhost:5140",
        host: "localhost:5140",
      })
    ).toBe("http://localhost:5140");
  });
});
