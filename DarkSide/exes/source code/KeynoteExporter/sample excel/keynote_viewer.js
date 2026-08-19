// EnneadTab Keynote Viewer JavaScript
// Interactive keynote hierarchy visualization with advanced search and navigation

function toggleAll(open) {
  document.querySelectorAll('details').forEach(d => d.open = open);
}

// Fuzzy matching function
function fuzzyMatch(text, query) {
  if (!query) return { match: true, score: 0 };
  
  const textLower = text.toLowerCase();
  const queryLower = query.toLowerCase();
  
  // Exact match gets highest score
  if (textLower.includes(queryLower)) {
    return { match: true, score: 100 };
  }
  
  // Fuzzy matching - check if all query characters appear in order
  let queryIndex = 0;
  let score = 0;
  
  for (let i = 0; i < textLower.length && queryIndex < queryLower.length; i++) {
    if (textLower[i] === queryLower[queryIndex]) {
      queryIndex++;
      score += 10;
      // Bonus for consecutive matches
      if (i > 0 && textLower[i-1] === queryLower[queryIndex-2]) {
        score += 5;
      }
    }
  }
  
  // Partial word matches
  const words = textLower.split(/\s+/);
  for (const word of words) {
    if (word.startsWith(queryLower)) {
      score += 20;
    }
  }
  
  return { match: queryIndex === queryLower.length, score: score };
}

// Highlight matching text
function highlightText(element, query) {
  if (!query) {
    // Remove existing highlights
    element.innerHTML = element.innerHTML.replace(/<span class="search-highlight">(.*?)<\/span>/gi, '$1');
    return;
  }
  
  const text = element.textContent;
  // Use simple string replacement to avoid regex issues
  const escapedQuery = query.replace(/[.*+?^${}()|[\]\\]/g, function(match) {
    return '\\' + match;
  });
  const regex = new RegExp('(' + escapedQuery + ')', 'gi');
  element.innerHTML = text.replace(regex, '<span class="search-highlight">$1</span>');
}

function filterTree() {
  const q = document.getElementById('search').value.trim();
  const divisions = document.querySelectorAll('[data-division]');
  
  // Clear previous highlights
  document.querySelectorAll('.search-highlight').forEach(el => {
    el.outerHTML = el.innerHTML;
  });
  
  if (!q) {
    // Show all items when search is empty
    divisions.forEach(div => {
      div.classList.remove('hidden');
      const sections = div.querySelectorAll('[data-section]');
      sections.forEach(sec => {
        sec.classList.remove('hidden');
        const items = sec.querySelectorAll('li');
        items.forEach(li => {
          li.classList.remove('hidden', 'search-match');
        });
      });
    });
    return;
  }
  
  divisions.forEach(div => {
    let divisionMatches = false;
    const sections = div.querySelectorAll('[data-section]');
    sections.forEach(sec => {
      let sectionMatches = false;
      const items = sec.querySelectorAll('li');
      items.forEach(li => {
        // Prefer matching against the concise header (key + desc)
        const header = li.querySelector('.node-header');
        const allText = (header ? header.textContent : li.textContent);
        const fuzzyResult = fuzzyMatch(allText, q);
        const match = fuzzyResult.match;
        
        li.classList.toggle('hidden', !match);
        li.classList.toggle('search-match', match);
        
        if (match) {
          sectionMatches = true;
          // Auto-expand the section when item matches
          sec.open = true;
          // Highlight only safe headline text to avoid breaking pills/badges
          const keyEl = li.querySelector('.key');
          const descEl = li.querySelector('.desc');
          if (keyEl) { highlightText(keyEl, q); }
          if (descEl) { highlightText(descEl, q); }
        }
      });
      
      // Check section header for matches
      const secHeader = sec.querySelector('summary');
      if (secHeader) {
        const secText = secHeader.textContent;
        const secFuzzyResult = fuzzyMatch(secText, q);
        if (secFuzzyResult.match) {
          sectionMatches = true;
          highlightText(secHeader, q);
        }
      }
      
      sec.classList.toggle('hidden', !sectionMatches);
      if (sectionMatches) {
        divisionMatches = true;
        // Auto-expand the division when section matches
        div.open = true;
      }
    });
    
    // Check division header for matches
    const divHeader = div.querySelector('summary');
    if (divHeader) {
      const divText = divHeader.textContent;
      const divFuzzyResult = fuzzyMatch(divText, q);
      if (divFuzzyResult.match) {
        divisionMatches = true;
        highlightText(divHeader, q);
      }
    }
    
    div.classList.toggle('hidden', !divisionMatches);
  });
}

// Context menu functionality
let contextMenu = null;

function createContextMenu() {
  if (contextMenu) return contextMenu;
  
  contextMenu = document.createElement('div');
  contextMenu.className = 'context-menu';
  contextMenu.style.display = 'none';
  
  const menuItems = [
    { text: '🔍 Focus Search', action: () => document.getElementById('search').focus() },
    { text: '⬆️ Return to Top', action: () => window.scrollTo({ top: 0, behavior: 'smooth' }) },
    { text: '📂 Expand All', action: () => toggleAll(true) },
    { text: '📁 Collapse All', action: () => toggleAll(false) },
    { text: '🧹 Clear Search', action: () => { document.getElementById('search').value = ''; filterTree(); } },
    { text: '🔄 Refresh View', action: () => location.reload() }
  ];
  
  menuItems.forEach(item => {
    const menuItem = document.createElement('div');
    menuItem.className = 'context-menu-item';
    menuItem.textContent = item.text;
    menuItem.onclick = () => {
      item.action();
      hideContextMenu();
    };
    contextMenu.appendChild(menuItem);
  });
  
  document.body.appendChild(contextMenu);
  return contextMenu;
}

function showContextMenu(event) {
  event.preventDefault();
  const menu = createContextMenu();
  menu.style.display = 'block';
  menu.style.left = event.pageX + 'px';
  menu.style.top = event.pageY + 'px';
  
  // Adjust position if menu would go off screen
  const rect = menu.getBoundingClientRect();
  if (rect.right > window.innerWidth) {
    menu.style.left = (event.pageX - rect.width) + 'px';
  }
  if (rect.bottom > window.innerHeight) {
    menu.style.top = (event.pageY - rect.height) + 'px';
  }
}

function hideContextMenu() {
  if (contextMenu) {
    contextMenu.style.display = 'none';
  }
}

// Sticky toolbar functionality
let scrollTimeout;
let isScrolling = false;

function handleScroll() {
  const toolbar = document.querySelector('.toolbar');
  const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
  
  // Clear existing timeout
  clearTimeout(scrollTimeout);
  
  // Add sticky class immediately when scrolling down
  if (scrollTop > 50) {
    toolbar.classList.add('sticky');
  } else {
    toolbar.classList.remove('sticky');
  }
  
  // Set timeout to remove sticky class when scrolling stops
  scrollTimeout = setTimeout(() => {
    if (scrollTop <= 50) {
      toolbar.classList.remove('sticky');
    }
  }, 150); // 150ms delay
}

// Event listeners
document.addEventListener('DOMContentLoaded', function() {
  // Context menu event listeners
  document.addEventListener('contextmenu', function(e) {
    e.preventDefault();
    showContextMenu(e);
  });
  
  document.addEventListener('click', function(e) {
    if (!e.target.closest('.context-menu')) {
      hideContextMenu();
    }
  });
  
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') hideContextMenu();
  });
  
  // Add scroll listener for sticky toolbar
  window.addEventListener('scroll', handleScroll, { passive: true });
});
