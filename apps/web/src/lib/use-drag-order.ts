"use client";

import { useRef, useState } from "react";

/**
 * Réordonnancement par glisser-déposer, accessible au clavier.
 *
 * Retourne les props à poser sur chaque ligne draggable et l'ordre courant.
 * `onReorder(newItems)` est appelé à chaque dépôt réussi.
 */
export function useDragOrder<T>(
  items: T[],
  getId: (item: T) => string,
  onReorder: (items: T[]) => void
) {
  const draggedId = useRef<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);

  function itemProps(id: string) {
    return {
      draggable: true,
      onDragStart: (e: React.DragEvent) => {
        draggedId.current = id;
        e.dataTransfer.effectAllowed = "move";
        try {
          e.dataTransfer.setData("text/plain", id);
        } catch {
          /* IE */
        }
      },
      onDragOver: (e: React.DragEvent) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        if (overId !== id) setOverId(id);
      },
      onDragLeave: () => {
        if (overId === id) setOverId(null);
      },
      onDrop: (e: React.DragEvent) => {
        e.preventDefault();
        setOverId(null);
        const from = draggedId.current;
        draggedId.current = null;
        if (!from || from === id) return;
        const next = [...items];
        const fromIdx = next.findIndex((i) => getId(i) === from);
        const toIdx = next.findIndex((i) => getId(i) === id);
        if (fromIdx < 0 || toIdx < 0) return;
        const [moved] = next.splice(fromIdx, 1);
        next.splice(toIdx, 0, moved);
        onReorder(next);
      },
      onDragEnd: () => {
        draggedId.current = null;
        setOverId(null);
      },
      "aria-grabbed": overId === id,
    } as React.HTMLAttributes<HTMLElement> & { draggable: boolean };
  }

  return { itemProps, overId };
}
