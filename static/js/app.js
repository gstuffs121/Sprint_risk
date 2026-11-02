/**
 * SprintAI Enterprise Frontend Controller
 */

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

  // Real-time AI Risk Simulator (if present on page)
  initAISimulator();
});

// Modal helpers
function openModal(id) {
  const modal = document.getElementById(id);
  if (modal) {
    modal.classList.add("open");
  }
}

function closeModal(id) {
  const modal = document.getElementById(id);
  if (modal) {
    modal.classList.remove("open");
  }
}

// Toast helper
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

// Interactive Real-Time AI Simulator
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
        complexity: complexitySlider ? complexitySlider.value : 3,
        priority: prioritySelect ? prioritySelect.value : "Medium",
        dependencies: dependenciesSlider ? dependenciesSlider.value : 1,
        days_remaining: daysSlider ? daysSlider.value : 7,
        team_workload: workloadSlider ? workloadSlider.value : 50
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
    }, 150);
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

// Kanban Status Update via AJAX
function updateTaskStatus(taskId, newStatus) {
  fetch(`/tasks/${taskId}/update-status`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Requested-With": "XMLHttpRequest"
    },
    body: JSON.stringify({ status: newStatus })
  })
    .then((res) => res.json())
    .then((data) => {
      if (data.status === "success") {
        showToast(`Task moved to ${newStatus.replace("_", " ").toUpperCase()}`, "success");
        // Reload after short delay to reflect across all counts and columns
        setTimeout(() => window.location.reload(), 450);
      } else {
        showToast(data.message || "Failed to update task", "danger");
      }
    })
    .catch((err) => {
      console.error(err);
      showToast("Error updating task status", "danger");
    });
}
