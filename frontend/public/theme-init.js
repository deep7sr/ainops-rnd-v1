// Applies the saved theme before the page is drawn, so it never flashes in the wrong colours.
// Loaded by index.html as a plain (blocking) script. Must match src/app/theme/theme-context.ts
// (storage key, values, default); src/app/theme/theme.test.tsx runs this file to check that.
;(function () {
  var choice = 'light'
  try {
    var saved = window.localStorage.getItem('ainops-theme')
    if (saved === 'light' || saved === 'dark' || saved === 'system') choice = saved
  } catch {
    // Storage can be blocked by browser settings: keep the default.
  }
  var dark =
    choice === 'dark' ||
    (choice === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.classList.toggle('dark', dark)
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
})()
