/** Tailwind build config for the Enikk web UI.
 *
 *  The compiled CSS is generated into enikk/static/vendor/tailwind.css by:
 *      npm run build        (from this directory)
 *
 *  Theme colors reference RGB-triplet CSS variables defined in
 *  enikk/static/css/styles.css so that opacity modifiers (bg-accent/10 etc.)
 *  work correctly and dark mode only needs to redefine the variables.
 */
module.exports = {
  darkMode: 'class',
  content: [
    '../enikk/static/index.html',
    '../enikk/static/loading.html',
    '../enikk/static/js/app.js',
    '../enikk/static/js/i18n.js',
    '../enikk/static/js/tips.js',
  ],
  theme: {
    extend: {
      colors: {
        sidebar: 'rgb(var(--c-sidebar-rgb) / <alpha-value>)',
        main:    'rgb(var(--c-bg-rgb) / <alpha-value>)',
        input:   'rgb(var(--c-input-rgb) / <alpha-value>)',
        border:  'rgb(var(--c-border-rgb) / <alpha-value>)',
        accent:  'rgb(var(--c-accent-rgb) / <alpha-value>)',
        hover:   'rgb(var(--c-hover-rgb) / <alpha-value>)',
        msguser: 'rgb(var(--c-input-rgb) / <alpha-value>)',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
