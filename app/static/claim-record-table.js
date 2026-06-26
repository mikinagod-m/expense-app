(function () {
  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function currency(v) {
    return `£${Number(v || 0).toFixed(2)}`;
  }

  function formatDateTime(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function capitalizeType(type) {
    if (!type) return "—";
    return type.charAt(0).toUpperCase() + type.slice(1);
  }

  const FINANCE_CATEGORIES = [
    { value: "hotel", label: "Hotel" },
    { value: "subsistence", label: "Subsistence" },
    { value: "travel", label: "Travel" },
    { value: "foreign_travel", label: "Foreign travel" },
    { value: "postage", label: "Postage" },
    { value: "staff_entertaining", label: "Staff entertaining" },
    { value: "customer_entertaining", label: "Customer entertaining" },
    { value: "other", label: "Other" },
    { value: "personal", label: "Personal" },
  ];

  function financeCategorySelect(line) {
    const lineId = line && line.id ? line.id : "";
    const current = (line && line.category_key) || "other";
    const options = FINANCE_CATEGORIES.map(
      (c) => `<option value="${c.value}"${c.value === current ? " selected" : ""}>${escapeHtml(c.label)}</option>`,
    ).join("");
    return `
      <select class="finance-amend-category" data-line-id="${lineId}" aria-label="Category for line ${lineId}">
        ${options}
      </select>`;
  }

  function financeDetailInput(line) {
    const lineId = line && line.id ? line.id : "";
    const value = escapeHtml((line && line.narrative) || "");
    return `
      <input type="text" class="finance-amend-detail" data-line-id="${lineId}"
             value="${value}" aria-label="Detail for line ${lineId}">`;
  }

  function financeAmendControls(line) {
    const lineId = line && line.id ? line.id : "";
    return `
      <div class="finance-amend-controls">
        <button type="button" class="btn ghost sm finance-amend-save" data-line-id="${lineId}">Save coding</button>
        <span class="finance-amend-status hint" data-line-id="${lineId}"></span>
      </div>`;
  }

  function receiptThumb(receipt) {
    if (!receipt) {
      return `<span class="small dim">—</span>`;
    }
    const label = escapeHtml(receipt.filename || "Receipt");
    if (receipt.is_image) {
      return `
        <button type="button" class="receipt-thumb-btn" title="View receipt"
                data-receipt-url="${escapeHtml(receipt.url)}"
                data-receipt-image="1"
                data-receipt-label="${label}">
          <img class="receipt-thumb" src="${escapeHtml(receipt.url)}" alt="" loading="lazy">
        </button>`;
    }
    return `
      <button type="button" class="receipt-thumb-btn receipt-pdf-btn" title="View receipt"
              data-receipt-url="${escapeHtml(receipt.url)}"
              data-receipt-pdf="1"
              data-receipt-label="${label}">PDF</button>`;
  }

  function flattenClaims(claims) {
    const rows = [];
    for (const claim of claims) {
      const lines = claim.lines && claim.lines.length ? claim.lines : [null];
      lines.forEach((line, index) => {
        rows.push({
          claim,
          line,
          isFirst: index === 0,
          span: lines.length,
        });
      });
    }
    return rows;
  }

  function lineCommentCell(claim, line) {
    const lineId = line && line.id ? line.id : "";
    const detail = line && line.narrative ? line.narrative : "item";
    const category = line && line.category ? line.category : "line";
    const ariaLabel = `Comment on ${category} — ${detail}`;
    return `
      <textarea class="decision-comment" data-claim-id="${claim.id}" data-line-id="${lineId}"
                maxlength="120" placeholder="Note for this item"
                aria-label="${escapeHtml(ariaLabel)}"></textarea>
      <div class="comment-counter">0/120</div>`;
  }

  function collectLineComments(claimId) {
    const parts = [];
    document.querySelectorAll(`.decision-comment[data-claim-id="${claimId}"]`).forEach((input) => {
      const text = input.value.trim();
      if (!text) return;
      const row = input.closest("tr");
      const detail = row?.querySelector('[data-l="Detail"]')?.textContent?.trim() || "Item";
      const category = row?.querySelector('[data-l="Category"]')?.textContent?.trim() || "";
      const label = category ? `${category} · ${detail}` : detail;
      parts.push({ label, text });
    });
    return parts;
  }

  function formatLineComments(parts) {
    return parts.map((part) => `${part.label}: ${part.text}`).join(" | ");
  }

  function claimActionCell(claim, actionHtml) {
    if (actionHtml) return actionHtml;
    return `
      <div class="approval-actions">
        <button type="button" class="btn approve sm" data-decide="${claim.id}" data-decision="approved">Approve</button>
        <button type="button" class="btn reject sm" data-decide="${claim.id}" data-decision="rejected">Reject</button>
      </div>`;
  }

  function renderRow(row, options = {}) {
    const {
      showComment = false,
      showActions = false,
      showApprovedBy = false,
      showStatus = false,
      showFinanceAmend = false,
      nameField = "claimant",
      clickable = false,
      actionHtml = null,
    } = options;
    const { claim, line, isFirst, span } = row;

    let nameCell = "";
    if (isFirst) {
      const nameHtml = nameField === "ref"
        ? `<strong class="ref">${escapeHtml(claim.ref || "Draft")}</strong>`
        : `<strong>${escapeHtml(claim.claimant_name || `User ${claim.user_id}`)}</strong>
           <span class="approval-ref ref">${escapeHtml(claim.ref || "—")}</span>`;
      nameCell = `<td data-l="Name" rowspan="${span}" class="approval-name">${nameHtml}</td>`;
    }

    let typeCell = "";
    if (isFirst) {
      typeCell = `<td data-l="Type" rowspan="${span}"><span class="pill submitted">${escapeHtml(capitalizeType(claim.type))}</span></td>`;
    }

    let submittedCell = "";
    if (isFirst) {
      submittedCell = `<td data-l="Submitted" rowspan="${span}" class="approval-submitted">${claim.submitted_at ? formatDateTime(claim.submitted_at) : escapeHtml(claim.posted_label || "—")}</td>`;
    }

    let statusCell = "";
    if (showStatus && isFirst) {
      statusCell = `<td data-l="Status" rowspan="${span}"><span class="pill ${escapeHtml(claim.status || "")}">${escapeHtml(claim.status || "—")}</span></td>`;
    }

    let approvedByCell = "";
    if (showApprovedBy && isFirst) {
      approvedByCell = `<td data-l="Approved by" rowspan="${span}">${escapeHtml(claim.approved_by_name || "—")}</td>`;
    }

    let commentCell = "";
    if (showComment) {
      commentCell = `<td data-l="Comment" class="approval-comment-cell">${lineCommentCell(claim, line)}</td>`;
    }

    let actionCell = "";
    if (showActions && isFirst) {
      actionCell = `<td data-l="Action" rowspan="${span}" class="approval-action-cell">${claimActionCell(claim, actionHtml)}</td>`;
    }

    const detail = line
      ? (showFinanceAmend ? financeDetailInput(line) : escapeHtml(line.narrative || "—"))
      : "—";
    const receiptRef = line ? escapeHtml(line.receipt_ref || "—") : "—";
    const category = line
      ? (showFinanceAmend
        ? `${financeCategorySelect(line)}${financeAmendControls(line)}`
        : escapeHtml(line.category || "—"))
      : "—";
    const amount = line ? currency(line.amount) : "—";
    const receipt = line ? receiptThumb(line.receipt) : `<span class="small dim">—</span>`;
    const rowClass = `${clickable ? "clickable " : ""}${isFirst ? "claim-start" : "claim-line"}${showFinanceAmend && line ? " finance-amend-row" : ""}`;
    const clickHandler = clickable && claim.id ? ` onclick="window.location.href='/claims/${claim.id}'"` : "";

    return `
      <tr data-claim-id="${claim.id}"${line && line.id ? ` data-line-id="${line.id}"` : ""} class="${rowClass}"${clickHandler}>
        ${nameCell}
        <td data-l="Detail">${detail}</td>
        <td data-l="Receipt ref" class="mono">${receiptRef}</td>
        <td data-l="Category">${category}</td>
        ${typeCell}
        <td class="amt r" data-l="Amount">${amount}</td>
        ${submittedCell}
        ${statusCell}
        ${approvedByCell}
        <td class="c receipt-cell" data-l="Receipt">${receipt}</td>
        ${commentCell}
        ${actionCell}
      </tr>`;
  }

  function bindCommentCounters(root) {
    root.querySelectorAll(".decision-comment").forEach((input) => {
      const counter = input.parentElement.querySelector(".comment-counter");
      if (!counter || input.dataset.counterBound === "1") return;
      const refresh = () => {
        counter.textContent = `${input.value.length}/120`;
      };
      input.addEventListener("input", refresh);
      input.dataset.counterBound = "1";
      refresh();
    });
  }

  function bindFinanceAmendControls(root, handler) {
    root.querySelectorAll(".finance-amend-save").forEach((btn) => {
      if (btn.dataset.bound === "1") return;
      btn.addEventListener("click", () => {
        handler(Number(btn.dataset.lineId));
      });
      btn.dataset.bound = "1";
    });
  }

  function setFinanceAmendStatus(lineId, text, type = "") {
    const node = document.querySelector(`.finance-amend-status[data-line-id="${lineId}"]`);
    if (!node) return;
    node.textContent = text;
    node.className = `finance-amend-status hint ${type}`.trim();
  }

  function readFinanceAmendValues(lineId) {
    const row = document.querySelector(`tr[data-line-id="${lineId}"]`);
    if (!row) return null;
    const detail = row.querySelector(".finance-amend-detail");
    const category = row.querySelector(".finance-amend-category");
    if (!detail || !category) return null;
    return {
      narrative: detail.value.trim(),
      category: category.value,
    };
  }

  function bindDecisionButtons(root, handler) {
    root.querySelectorAll("[data-decide]").forEach((btn) => {
      if (btn.dataset.bound === "1") return;
      btn.addEventListener("click", () => {
        handler(Number(btn.dataset.decide), btn.dataset.decision);
      });
      btn.dataset.bound = "1";
    });
  }

  function historyLineToRow(item) {
    const claim = {
      id: item.claimId,
      ref: item.ref,
      type: item.type,
      status: item.status,
      submitted_at: item.submittedAt,
      posted_label: item.postedLabel,
      approved_by_name: item.approvedBy,
    };
    const line = {
      narrative: item.detail,
      receipt_ref: item.receiptRef,
      category: item.category,
      amount: item.amount,
      receipt: item.receipt,
    };
    return { claim, line, isFirst: true, span: 1 };
  }

  window.ClaimRecordTable = {
    escapeHtml,
    currency,
    formatDateTime,
    flattenClaims,
    renderRow,
    bindCommentCounters,
    bindDecisionButtons,
    collectLineComments,
    formatLineComments,
    bindFinanceAmendControls,
    setFinanceAmendStatus,
    readFinanceAmendValues,
    FINANCE_CATEGORIES,
    historyLineToRow,
    receiptThumb,
  };
})();
