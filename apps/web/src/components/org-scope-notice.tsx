"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

type Me = { id: string; role: string; org_id: string | null };

/**
 * Bannière affichée quand le compte connecté est superadmin sans organisation :
 * les opérations liées au contenu (sites, médias, playlists…) sont scopées à
 * une organisation côté API. Le superadmin doit créer une organisation, un
 * admin organisation (page Utilisateurs) puis se connecter avec ce compte.
 */
export function OrgScopeNotice() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    api
      .get<Me>("/api/auth/me")
      .then((me) => setShow(me.role === "superadmin"))
      .catch(() => setShow(false));
  }, []);

  if (!show) {
    return null;
  }

  return (
    <div className="rounded-md border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
      Vous êtes connecté en <strong>superadmin</strong> (compte hors organisation).
      Les sites, médias et contenus sont rattachés à une organisation : créez-en
      une ainsi qu&apos;un administrateur d&apos;organisation dans{" "}
      <Link href="/users" className="font-medium underline">
        Utilisateurs
      </Link>
      , puis reconnectez-vous avec ce compte pour gérer le contenu.
    </div>
  );
}
