export function shouldShowTopBar(chatStarted: boolean): boolean {
  return chatStarted;
}

export function shouldShowStandaloneHistoryToggle(
  _chatStarted: boolean,
): boolean {
  return true;
}
