let counter = 0;

/** Short, stable-enough id for new LD/SFC document nodes (IDE-local, not protocol data). */
export function newId(prefix: string): string {
  counter += 1;
  return `${prefix}_${Date.now().toString(36)}${counter.toString(36)}`;
}
