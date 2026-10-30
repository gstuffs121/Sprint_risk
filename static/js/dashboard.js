
document.addEventListener("DOMContentLoaded", () => {
    // Mobile sidebar
    const menuToggle = document.getElementById("menuToggle");
    const sidebar = document.getElementById("sidebar");

    if (menuToggle && sidebar) {
        menuToggle.addEventListener("click", () => {
            sidebar.classList.toggle("open");
        });

        document.addEventListener("click", (event) => {
            if (
                window.innerWidth <= 760 &&
                sidebar.classList.contains("open") &&
                !sidebar.contains(event.target) &&
                !menuToggle.contains(event.target)
            ) {
                sidebar.classList.remove("open");
            }
        });
    }

    // Dashboard sprint status chart
    const chartCanvas = document.getElementById("sprintStatusChart");

    if (chartCanvas && typeof Chart !== "undefined") {
        fetch("/api/chart-data")
            .then((response) => {
                if (!response.ok) {
                    throw new Error("Unable to load chart data");
                }
                return response.json();
            })
            .then((data) => {
                const values = [
                    Number(data.todo || 0),
                    Number(data.in_progress || 0),
                    Number(data.completed || 0)
                ];

                new Chart(chartCanvas, {
                    type: "doughnut",
                    data: {
                        labels: ["To Do", "In Progress", "Completed"],
                        datasets: [{
                            data: values,
                            backgroundColor: ["#e7e5f5", "#f4bd62", "#6558e8"],
                            borderWidth: 0,
                            hoverOffset: 6
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        cutout: "73%",
                        plugins: {
                            legend: {
                                position: "bottom",
                                labels: {
                                    usePointStyle: true,
                                    pointStyle: "circle",
                                    padding: 20,
                                    color: "#777994",
                                    font: { size: 11 }
                                }
                            }
                        }
                    }
                });
            })
            .catch((error) => {
                console.error("Dashboard chart error:", error);
            });
    }

    // Prevent accidental double submission of forms
    document.querySelectorAll("form[data-loading-button]").forEach((form) => {
        form.addEventListener("submit", () => {
            const button = form.querySelector('button[type="submit"]');
            if (button && form.checkValidity()) {
                button.disabled = true;
                button.textContent = "Please wait...";
            }
        });
    });
});
