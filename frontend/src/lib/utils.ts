export function joinStorageUrl(path: string) {
  // Backend should serve static:
  // app.mount("/static", StaticFiles(directory="."), name="static")
  // Then "storage/..." becomes "/static/storage/..."
  return `/static/${path}`.replaceAll("//", "/");
}

export function cn(...classes: Array<string | undefined | null | false>) {
  return classes.filter(Boolean).join(" ");
}
