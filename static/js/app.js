/**
 * SprintAI Enterprise Frontend Controller
 * Robust AJAX operations, HTML5 Drag & Drop Kanban, and real-time ML risk simulation.
 */

let draggedTaskId = null;

document.addEventListener("DOMContentLoaded", function () {
  // Mobile sidebar toggle
  const menuToggle = document.getElementById("menuToggle");
  const sidebar = document.getElementById("sidebar");

  if (menuToggle && sidebar) {
    menuToggle.addEventListener("click", () => {
      sidebar.classList.toggle("open");
    });

    document.addEventListener("click", (e) => {
      if (
        window.innerWidth <= 768 &&
        sidebar.classList.contains("open") &&
        !sidebar.contains(e.target) &&
        !menuToggle.contains(e.target)
      ) {
        sidebar.classList.remove("open");
      }
    });
  }

  // Toast Auto-Dismiss
  document.querySelectorAll(".toast").forEach((toast) => {
    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateY(10px)";
      toast.style.transition = "all 0.3s ease";
      setTimeout(() => toast.remove(), 300);
    }, 4500);
  });

  // Modal Triggers
  document.querySelectorAll("[data-modal-target]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetId = btn.getAttribute("data-modal-target");
      openModal(targetId);
    });
  });

  document.querySelectorAll(".modal-close, [data-modal-close]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const modal = btn.closest(".modal-overlay");
      if (modal) modal.classList.remove("open");
    });
  });

  document.querySelectorAll(".modal-overlay").forEach((overlay) => {
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) overlay.classList.remove("open");
    });
  });

  // Global Keyboard Shortcuts
  document.addEventListener("keydown", function (e) {
    const activeTag = (document.activeElement.tagName || "").toLowerCase();
    const isEditing = ["input", "textarea", "select"].includes(activeTag) || document.activeElement.isContentEditable;

    // Press 'c' or 'C' to open quick create task modal
    if (!isEditing && (e.key === "c" || e.key === "C")) {
      e.preventDefault();
      openModal("quickTaskModal");
    }

    // Press 'Escape' to close all open modals
    if (e.key === "Escape") {
      document.querySelectorAll(".modal-overlay.open").forEach((m) => m.classList.remove("open"));
    }
  });

  // Real-time AI Risk Simulator
  initAISimulator();

  // Initialize Lucide icons if present
  if (typeof lucide !== "undefined") {
    lucide.createIcons();
  }
});

// Modal helpers
function openModal(id) {
  const modal = document.getElementById(id);
  if (modal) {
    modal.classList.add("open");
    const firstInput = modal.querySelector("input:not([type=hidden]), textarea, select");
    if (firstInput) firstInput.focus();
    if (typeof lucide !== "undefined") lucide.createIcons();
  }
}

function closeModal(id) {
  const modal = document.getElementById(id);
  if (modal) {
    modal.classList.remove("open");
  }
}

// Toast notification helper
function showToast(message, type = "info") {
  let container = document.querySelector(".toast-container");
  if (!container) {
    container = document.createElement("div");
    container.className = "toast-container";
    document.body.appendChild(container);
  }

  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <span style="font-weight:700;">${type === "success" ? "✓" : type === "danger" ? "✕" : "ℹ"}</span>
    <span style="font-size:13px;">${message}</span>
  `;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transition = "all 0.3s ease";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// =========================================================
// HTML5 DRAG & DROP KANBAN BOARD CONTROLLER
// =========================================================

function handleDragStart(e) {
  const card = e.currentTarget;
  draggedTaskId = card.getAttribute("data-task-id");
  card.classList.add("dragging");
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("text/plain", draggedTaskId);
}

function handleDragEnd(e) {
  const card = e.currentTarget;
  card.classList.remove("dragging");
  document.querySelectorAll(".kanban-col").forEach((col) => col.classList.remove("drag-over"));
}

function handleDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = "move";
  const col = e.currentTarget;
  if (!col.classList.contains("drag-over")) {
    col.classList.add("drag-over");
  }
}

function handleDragLeave(e) {
  const col = e.currentTarget;
  // Verify we actually left the column
  if (!col.contains(e.relatedTarget)) {
    col.classList.remove("drag-over");
  }
}

function handleDrop(e, targetStatus) {
  e.preventDefault();
  const col = e.currentTarget;
  col.classList.remove("drag-over");

  const taskId = e.dataTransfer.getData("text/plain") || draggedTaskId;
  if (!taskId) return;

  const card = document.getElementById("task-card-" + taskId);
  if (!card) return;

  const currentStatus = card.getAttribute("data-current-status");
  if (currentStatus === targetStatus) return;

  // Optimistic Move into target dropzone
  const targetZone = document.getElementById("zone-" + targetStatus);
  if (targetZone) {
    const emptyHint = targetZone.querySelector(".kanban-empty-hint");
    if (emptyHint) emptyHint.remove();
    targetZone.prepend(card);
    card.setAttribute("data-current-status", targetStatus);

    // Update the dropdown within the card to match new status
    const statusSelect = card.querySelector("select");
    if (statusSelect) statusSelect.value = targetStatus;
  }

  // Persist to backend via AJAX
  updateTaskStatus(taskId, targetStatus, false);
}

// =========================================================
// TASK STATUS PERSISTENCE (AJAX)
// =========================================================

function updateTaskStatus(taskId, newStatus, reloadOnSuccess = true) {
  fetch(`/tasks/${taskId}/update-status`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Requested-With": "XMLHttpRequest"
    },
    body: JSON.stringify({ status: newStatus })
  })
    .then((res) => {
      if (!res.ok) throw new Error("Server returned status " + res.status);
      return res.json();
    })
    .then((data) => {
      if (data.status === "success") {
        const readable = newStatus.replace("_", " ").toUpperCase();
        showToast(`Task #${taskId} moved to ${readable}`, "success");
        updateColumnCounts();
        if (reloadOnSuccess) {
          setTimeout(() => window.location.reload(), 400);
        }
      } else {
        showToast(data.message || "Failed to update task", "danger");
      }
    })
    .catch((err) => {
      console.error(err);
      showToast("Error persisting task status: " + err.message, "danger");
    });
}

function updateColumnCounts() {
  document.querySelectorAll(".kanban-col").forEach((col) => {
    const status = col.getAttribute("data-column-status");
    const countBadge = col.querySelector(".col-count");
    const dropzone = col.querySelector(".kanban-dropzone");
    if (dropzone && countBadge) {
      const cards = dropzone.querySelectorAll(".kanban-card");
      countBadge.textContent = cards.length;
    }
  });
}

// =========================================================
// REAL-TIME ML PREDICTION SIMULATOR
// =========================================================

function initAISimulator() {
  const simForm = document.getElementById("aiSimulatorForm");
  if (!simForm) return;

  const complexitySlider = document.getElementById("simComplexity");
  const prioritySelect = document.getElementById("simPriority");
  const dependenciesSlider = document.getElementById("simDependencies");
  const daysSlider = document.getElementById("simDays");
  const workloadSlider = document.getElementById("simWorkload");

  const effortOutput = document.getElementById("simEffortOutput");
  const riskPercentOutput = document.getElementById("simRiskPercent");
  const riskLevelOutput = document.getElementById("simRiskLevel");
  const riskBar = document.getElementById("simRiskBar");

  let debounceTimer = null;

  function runSimulation() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      const payload = {
        complexity: complexitySlider ? parseInt(complexitySlider.value) : 3,
        priority: prioritySelect ? prioritySelect.value : "Medium",
        dependencies: dependenciesSlider ? parseInt(dependenciesSlider.value) : 1,
        days_remaining: daysSlider ? parseInt(daysSlider.value) : 7,
        team_workload: workloadSlider ? parseInt(workloadSlider.value) : 50
      };

      fetch("/api/predict", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      })
        .then((res) => res.json())
        .then((data) => {
          if (data.status === "success") {
            if (effortOutput) effortOutput.textContent = data.predicted_hours + "h";
            if (riskPercentOutput) riskPercentOutput.textContent = data.risk_probability + "%";

            if (riskLevelOutput) {
              riskLevelOutput.textContent = data.risk_level;
              riskLevelOutput.className = `badge badge-${data.risk_level.toLowerCase()}`;
            }

            if (riskBar) {
              riskBar.style.width = data.risk_probability + "%";
              if (data.risk_probability < 25) {
                riskBar.style.background = "var(--success)";
              } else if (data.risk_probability < 50) {
                riskBar.style.background = "var(--accent)";
              } else if (data.risk_probability < 75) {
                riskBar.style.background = "var(--warning)";
              } else {
                riskBar.style.background = "var(--danger)";
              }
            }
          }
        })
        .catch((err) => console.error("Simulator API error:", err));
    }, 120);
  }

  // Update slider labels and trigger simulation on change
  [complexitySlider, dependenciesSlider, daysSlider, workloadSlider].forEach((slider) => {
    if (slider) {
      slider.addEventListener("input", (e) => {
        const valSpan = document.getElementById(slider.id + "Val");
        if (valSpan) valSpan.textContent = e.target.value;
        runSimulation();
      });
    }
  });

  if (prioritySelect) {
    prioritySelect.addEventListener("change", runSimulation);
  }

  // Initial call
  runSimulation();
}
