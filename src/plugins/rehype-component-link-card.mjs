/// <reference types="mdast" />
import { h } from "hastscript";

/**
 * Creates a Link Card component that fetches and displays metadata from a URL.
 *
 * @param {Object} properties - The properties of the component.
 * @param {string} properties.url - The URL to create a card for.
 * @param {import('mdast').RootContent[]} children - The children elements (should be empty).
 * @returns {import('mdast').Parent} The created Link Card component.
 */
export function LinkCardComponent(properties, children) {
	if (Array.isArray(children) && children.length !== 0)
		return h("div", { class: "hidden" }, [
			'Invalid directive. ("link" directive must be leaf type "::link{url=\\"https://example.com\\"}")',
		]);

	if (!properties.url || !properties.url.match(/^https?:\/\//))
		return h(
			"div",
			{ class: "hidden" },
			'Invalid URL. ("url" attribute must start with http:// or https://)',
		);

	const url = properties.url;
	const cardUuid = `LC${Math.random().toString(36).slice(-6)}`; // Collisions are not important

	const nImage = h(`div#${cardUuid}-image`, { class: "lc-image" });
	const nTitle = h(`div#${cardUuid}-title`, { class: "lc-title" }, "Loading...");
	const nDescription = h(
		`div#${cardUuid}-description`,
		{ class: "lc-description" },
		"Fetching metadata...",
	);
	const nDomain = h(`div#${cardUuid}-domain`, { class: "lc-domain" });

	const nScript = h(
		`script#${cardUuid}-script`,
		{ type: "text/javascript", defer: true },
		`
      (async () => {
        try {
          const response = await fetch('https://unfurl.dev/api/unfurl?url=' + encodeURIComponent('${url}'));
          const data = await response.json();
          
          const titleEl = document.getElementById('${cardUuid}-title');
          const descEl = document.getElementById('${cardUuid}-description');
          const imageEl = document.getElementById('${cardUuid}-image');
          const domainEl = document.getElementById('${cardUuid}-domain');
          const cardEl = document.getElementById('${cardUuid}-card');
          
          titleEl.innerText = data.title || '${url}';
          descEl.innerText = data.description || 'No description available';
          domainEl.innerText = new URL('${url}').hostname;
          
          if (data.favicon) {
            imageEl.style.backgroundImage = 'url(' + data.favicon + ')';
            imageEl.style.backgroundSize = 'contain';
            imageEl.style.backgroundPosition = 'center';
          } else if (data.open_graph?.image) {
            imageEl.style.backgroundImage = 'url(' + data.open_graph.image + ')';
            imageEl.style.backgroundSize = 'cover';
          }
          
          cardEl.classList.remove('fetch-waiting');
          console.log('[LINK-CARD] Loaded card for ${url} | ${cardUuid}.');
        } catch (err) {
          const cardEl = document.getElementById('${cardUuid}-card');
          cardEl?.classList.add('fetch-error');
          console.warn('[LINK-CARD] (Error) Loading card for ${url} | ${cardUuid}.');
        }
      })();
    `,
	);

	return h(
		`a#${cardUuid}-card`,
		{
			class: "card-link fetch-waiting no-styling",
			href: url,
			target: "_blank",
			rel: "noopener noreferrer",
		},
		[nImage, nTitle, nDescription, nDomain, nScript],
	);
}
