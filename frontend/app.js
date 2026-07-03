// Frontend script for Expense Auditor Dashboard
// Handles query submission, calls backend API, and displays results.
document.addEventListener('DOMContentLoaded', () => {
  const runBtn = document.getElementById('run-query');
  const queryInput = document.getElementById('query-input');
  const resultBox = document.getElementById('query-result');
  const overviewBox = document.getElementById('overview-data');

  // Load overview data on startup (optional placeholder)
  overviewBox.textContent = 'Ready to run queries.';

  runBtn.addEventListener('click', async () => {
    const query = queryInput.value.trim();
    if (!query) {
      resultBox.textContent = 'Please enter a query.';
      return;
    }
    resultBox.textContent = 'Running...';
    try {
      const response = await fetch('http://127.0.0.1:8000/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: query
        })
      });
      if (!response.ok) {
        const err = await response.json();
        resultBox.textContent = `Error: ${err.detail || response.statusText}`;
        return;
      }
      const data = await response.json();
      if (data.success) {
        resultBox.textContent = data.report;
      } else {
        resultBox.textContent = 'Unexpected response format.';
      }
    } catch (e) {
      resultBox.textContent = `Request failed: ${e}`;
    }
  });
});
