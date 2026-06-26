(async function loadNavBadges() {
  try {
    const response = await fetch("/nav/badges");
    if (!response.ok) {
      return;
    }
    const data = await response.json();
    if (!data.ok) {
      return;
    }

    const setBadge = (id, count) => {
      const node = document.getElementById(id);
      if (!node || !count || count < 1) {
        return;
      }
      node.textContent = String(count);
      node.hidden = false;
    };

    setBadge("nav-badge-approvals", data.pending_approvals);
    setBadge("nav-badge-approvals-mobile", data.pending_approvals);
    setBadge("nav-badge-finance", data.finance_approved);
    setBadge("nav-badge-finance-mobile", data.finance_approved);
  } catch (_error) {
    // Badges are optional polish; ignore network errors.
  }
})();
