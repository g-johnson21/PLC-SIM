// RFC 6901 JSON pointer helpers for mapping CompileError.path onto a document.
function splitPointer(pointer: string): string[] {
  if (!pointer || pointer === '/') return [];
  const raw = pointer.startsWith('/') ? pointer.slice(1) : pointer;
  return raw.split('/').map((p) => p.replace(/~1/g, '/').replace(/~0/g, '~'));
}

export function getByPointer(doc: unknown, pointer: string): unknown {
  const parts = splitPointer(pointer);
  let cur: unknown = doc;
  for (const part of parts) {
    if (cur == null) return undefined;
    cur = (cur as Record<string, unknown>)[part];
  }
  return cur;
}

/** Walk from the pointer's target up toward the document root and return the id of
 *  the nearest ancestor object that carries a stable "id" field, for highlighting an
 *  LD/SFC element from a CompileError whose path may point at a leaf field. */
export function nearestIdForPointer(doc: unknown, pointer: string): string | undefined {
  const parts = splitPointer(pointer);
  for (let i = parts.length; i >= 0; i -= 1) {
    const node = i === 0 ? doc : getByPointer(doc, '/' + parts.slice(0, i).join('/'));
    if (node && typeof node === 'object' && typeof (node as Record<string, unknown>).id === 'string') {
      return (node as Record<string, unknown>).id as string;
    }
  }
  return undefined;
}
