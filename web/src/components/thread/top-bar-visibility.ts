export function shouldShowTopBar(chatStarted: boolean): boolean {
  return chatStarted;
}

export function shouldShowStandaloneHistoryToggle(
  chatStarted: boolean,
): boolean {
  return !chatStarted;
}
