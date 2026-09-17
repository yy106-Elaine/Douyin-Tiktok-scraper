package edu.wellesley.scraper.parser

/**
 * Looks for a video id already present on screen.
 *
 * Reading the id passively is worth a lot: it needs no interaction with
 * the app, so it sends no engagement signal and cannot alter what the
 * recommender serves next. Both platforms use 19-digit snowflake ids
 * that currently begin with 7, which is a distinctive enough shape to
 * recognise wherever it turns up -- a view id, a text node, or a
 * content description.
 *
 * Whether either app exposes it at all is an open question; this
 * reports what it finds so the answer comes from a device rather than
 * from assumption.
 */
object IdScanner {

    /** Current-era ids: 19 digits starting with 7. */
    private val STRONG = Regex("""(?<!\d)(7\d{18})(?!\d)""")

    /** Any 18-19 digit run, in case the era prefix changes. */
    private val WEAK = Regex("""(?<!\d)(\d{18,19})(?!\d)""")

    data class Hit(val value: String, val where: String, val strong: Boolean)

    /** Every id-shaped token in these nodes, strongest first. */
    fun scan(nodes: List<FlatNode>): List<Hit> {
        val hits = LinkedHashMap<String, Hit>()

        for (node in nodes) {
            val sources = listOf(
                "viewId" to node.viewId,
                "text" to node.text,
                "desc" to node.description,
            )
            for ((where, value) in sources) {
                if (value == null) continue
                for (match in STRONG.findAll(value)) {
                    val id = match.groupValues[1]
                    if (!hits.containsKey(id)) {
                        hits[id] = Hit(id, where, strong = true)
                    }
                }
                for (match in WEAK.findAll(value)) {
                    val id = match.groupValues[1]
                    if (!hits.containsKey(id)) {
                        hits[id] = Hit(id, where, strong = false)
                    }
                }
            }
        }

        return hits.values.sortedByDescending { it.strong }
    }

    /** The best single candidate, or null when nothing id-shaped is present. */
    fun bestId(nodes: List<FlatNode>): String? = scan(nodes).firstOrNull()?.value

    /** A line for the self-check panel, so the answer comes from a device. */
    fun describe(nodes: List<FlatNode>): String {
        val hits = scan(nodes)
        if (hits.isEmpty()) return "no id-shaped token on screen"
        return hits.take(3).joinToString("; ") {
            "${it.value} (${it.where}${if (it.strong) "" else ", weak"})"
        }
    }
}
