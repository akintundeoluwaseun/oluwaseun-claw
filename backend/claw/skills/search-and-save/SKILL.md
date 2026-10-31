---
name: search-and-save
description: Search the web, open a good result and save its title and link, or save useful links to a file.
triggers: search the web, look up, find online, save the link, save its title
---
1. web_search with a short query.
2. open_search_result with the number of the best result.
3. save_links with the result's title and its exact address, e.g.
   {"file_name": "video editors", "links": [{"title": "OpenShot Video Editor", "url": "https://www.openshot.org/"}]}
   Only addresses you actually saw can be saved.
4. Say where the file was saved.
