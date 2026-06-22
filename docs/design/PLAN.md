# QMA UI Redesign & Responsiveness Plan

This document outlines the proposed layout adjustments, UX enhancements, and responsiveness plan for the **Quant Memory Agent (QMA)** dashboard.

---

## 🎨 Proposed Visual Direction

We have designed a visual mockup showing a premium dark-mode interface with a glassmorphic aesthetic. Key design details:
- **HSL-Based Color System**: Utilizing a consistent color hierarchy—deep slate background, glowing violet borders for active states, vibrant mint green (`#22d3a0`) for actions/success, and warnings in red.
- **Glassmorphism**: Transparent background cards with clean backdrops to separate visual segments.
- **Clean Typography**: Inter for interfaces/labels, JetBrains Mono for data displays and inputs.

Here is the mockup generated for the new look:
![Proposed QMA UI Mockup](file:///C:/Users/Admin/.gemini/antigravity-ide/brain/a39ef0d4-ef3d-4a83-8d66-0875911fb774/qma_redesign_mockup_1782019214989.png)

---

## 🛠️ Key Structural Improvements

### 1. Header Decluttering (Status & Stats Consolidation)
*   **Current Issue**: The header contains 6 separate badge items stretching across the top, showing engine stats (`Ledoit-Wolf Active`, `Half-life`), platform metrics (`Paid`, `Rev`), and seller details (`Avail`, `Batch`). This is overwhelming for buyers.
*   **Solution**: Group these indicators into a single, clean **"Status & Metrics"** dropdown popover button on the right.
    *   **Main Header**: Brand logo, Navigation Links (`App`, `Marketplace`, `API Docs`), Clock, Status Dropdown, and Connect Wallet button.
    *   **Dropdown Card Content**:
        *   **Engine Diagnostics**: Ledoit-Wolf Active indicator, Half-life.
        *   **Platform Stats**: Total paid reports, total platform revenue.
        *   **Seller Treasury**: Confirmations, available balance, and pending batch.
    *   *Note: All original DOM element IDs (`metrics-payments`, `metrics-revenue`, `metrics-balance`, etc.) will be preserved inside the dropdown, ensuring no API bindings are broken.*

### 2. Query Form Grid Layout
*   **Current Issue**: The query input fields stretch horizontally in a single strip containing 8 narrow columns. On medium/small screens, it wraps poorly, causing spacing and sizing alignment failures.
*   **Solution**: Reorganize the form into a clean, grid-based card layout.
    *   On desktop: Compact 4-column or 3-column input card grid.
    *   On tablets/mobile: Adapts automatically to 2-column or 1-column layout.
    *   Enlarge input touch targets and add subtle neon border glow indicators on focus.

### 3. Responsive Workspace (Mobile/Tablet Layouts)
*   **Current Issue**: The workspace assumes a fixed side-by-side flex layout which breaks on screens below 1200px width.
*   **Solution**: Add responsive CSS media queries:
    *   **Screens < 1024px**:
        *   The left sidebar (`Live Feed` / `Agent Picks`) and main panel are placed in a responsive stack.
        *   Implement a **Mobile Navigation Bar** or a Tab-Switch Toggle (**"Live Signals"** vs **"Analysis Report"**) to allow users to switch tabs smoothly on mobile, maximizing screenspace.
    *   **Tables**: Ensure all data tables (`Closest Historical Funding Events`, `Recent Settlements`, etc.) are wrapped in overflow-x scroll containers so they do not break boundaries on portrait phone view.

---

## 🚀 Execution Strategy under `/design`

To prevent any disruptions to the active workspace, we will create a dedicated `/design` folder:
1.  **`design/app.html`**: A copy of the application dashboard incorporating the consolidated header dropdown, grid query editor, and tab-switching elements.
2.  **`design/design_styles.css`**: A premium CSS stylesheet overriding the current terminal design, focusing on glassmorphism, responsive queries, transitions, and glow states.
3.  **`design/app.js`**: Reuses the core JS logic with minor UI integrations (such as opening the Status dropdown or handling Mobile tab switching) without breaking API payload mapping.
