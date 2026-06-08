import { h } from "hastscript";
import { visit } from "unist-util-visit";

const USER_AGENT =
	"Mozilla/5.0 (compatible; Calc1teLinkCard/1.0; +https://calc1te.github.io/)";
const metadataCache = new Map();

function getMetaContent(html, selectors) {
	for (const selector of selectors) {
		const pattern = new RegExp(
			`<meta\\s+[^>]*(?:property|name)=["']${selector}["'][^>]*content=["']([^"']*)["'][^>]*>|<meta\\s+[^>]*content=["']([^"']*)["'][^>]*(?:property|name)=["']${selector}["'][^>]*>`,
			"i",
		);
		const match = html.match(pattern);
		if (match?.[1] || match?.[2]) return decodeHtml(match[1] || match[2]);
	}
	return "";
}

function getTitle(html) {
	const match = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
	return match ? decodeHtml(match[1].replace(/\s+/g, " ").trim()) : "";
}

function getFavicon(html, pageUrl) {
	const match = html.match(
		/<link\s+[^>]*rel=["'][^"']*(?:icon|shortcut icon|apple-touch-icon)[^"']*["'][^>]*href=["']([^"']+)["'][^>]*>/i,
	);
	if (!match?.[1]) return "";
	return toAbsoluteUrl(match[1], pageUrl);
}

function toAbsoluteUrl(value, pageUrl) {
	try {
		return new URL(value, pageUrl).toString();
	} catch {
		return "";
	}
}

function decodeHtml(value) {
	return value
		.replace(/&amp;/g, "&")
		.replace(/&lt;/g, "<")
		.replace(/&gt;/g, ">")
		.replace(/&quot;/g, '"')
		.replace(/&#39;/g, "'")
		.trim();
}

async function fetchMetadata(url) {
	if (metadataCache.has(url)) return metadataCache.get(url);

	const response = await fetch(url, {
		headers: {
			"user-agent": USER_AGENT,
			accept: "text/html,application/xhtml+xml",
		},
		signal: AbortSignal.timeout(10_000),
	});

	if (!response.ok) throw new Error(`HTTP ${response.status}`);

	const html = await response.text();
	const title =
		getMetaContent(html, ["og:title", "twitter:title"]) ||
		getTitle(html) ||
		url;
	const description = getMetaContent(html, [
		"og:description",
		"twitter:description",
		"description",
	]);
	const image =
		toAbsoluteUrl(
			getMetaContent(html, ["og:image", "twitter:image", "twitter:image:src"]),
			url,
		) || getFavicon(html, url);

	const metadata = {
		title,
		description,
		image,
		domain: new URL(url).hostname,
	};
	metadataCache.set(url, metadata);
	return metadata;
}

function createCard(url, metadata) {
	const imageStyle = metadata.image
		? `background-image: url("${metadata.image}"); background-size: cover;`
		: "";

	return h(
		"a",
		{
			class: "card-link no-styling",
			href: url,
			target: "_blank",
			rel: "noopener noreferrer",
		},
		[
			h("div", { class: "lc-image", style: imageStyle }),
			h("div", {}, [
				h("div", { class: "lc-title" }, metadata.title || url),
				h(
					"div",
					{ class: "lc-description" },
					metadata.description || "No description available",
				),
				h("div", { class: "lc-domain" }, metadata.domain),
			]),
		],
	);
}

export function rehypeLinkCardMetadata() {
	return async (tree) => {
		const tasks = [];

		visit(tree, "element", (node, index, parent) => {
			if (node.tagName !== "link" || !parent || index == null) return;

			const url = node.properties?.url;
			if (typeof url !== "string" || !/^https?:\/\//.test(url)) return;

			tasks.push(
				(async () => {
					let metadata;
					try {
						metadata = await fetchMetadata(url);
					} catch (error) {
						console.warn(
							`[LINK-CARD] Failed to fetch metadata for ${url}: ${error}`,
						);
						metadata = {
							title: url,
							description: "No description available",
							image: "",
							domain: new URL(url).hostname,
						};
					}

					parent.children[index] = createCard(url, metadata);
				})(),
			);
		});

		await Promise.all(tasks);
	};
}
