import regex as re
from typing import List, Tuple
from functools import lru_cache

# Separator weight constants
WEIGHTS = (4, 3, 2, 1, 0)
(
    PARAGRAPH_SEPARATOR_WEIGHT,
    SENTENCE_TERMINATOR_WEIGHT,
    OTHER_PUNCTUATION_WEIGHT,
    SPACE_WEIGHT,
    NO_WEIGHT,
) = WEIGHTS


@lru_cache(maxsize=4096)
def get_weight(char: str) -> int:
    """Determine the weight of a character for splitting purposes."""
    if re.match(r"[\n\r]|\p{Zl}|\p{Zp}", char):
        return PARAGRAPH_SEPARATOR_WEIGHT
    elif re.match(r"\p{STerm}", char):
        return SENTENCE_TERMINATOR_WEIGHT
    elif re.match(r"\p{Po}", char):
        return OTHER_PUNCTUATION_WEIGHT
    elif re.match(r"\p{Zs}", char):
        return SPACE_WEIGHT
    return NO_WEIGHT


def split_text_into_chunks(
    text: str, tokenizer, max_tokens: int, optimize=True
) -> List[Tuple[int, str, int]]:
    """Split text into chunks based on separator weights and token limits.

    Args:
        text: Input text to be split
        tokenizer: Tokenizer object with encode method
        max_tokens: Maximum number of tokens per chunk

    Returns:
        List of tuples containing (start_index, chunk_text, token_count)
    """
    if not isinstance(max_tokens, int) or max_tokens <= 0:
        raise ValueError("max_tokens must be a positive integer")

    def get_token_count(segment: str) -> int:
        """Get token count for a text segment."""
        return len(
            tokenizer.encode(
                segment,
                add_special_tokens=True,
                truncation=True,
                max_length=max_tokens + 1,
            )
        )

    def optimize_chunks(
        chunks: List[Tuple[int, str, int]],
    ) -> List[Tuple[int, str, int]]:
        """Optimize chunks to ensure maximum token utilization."""
        if len(chunks) <= 1:
            return chunks

        optimized: List[Tuple[int, str, int]] = []
        i = 0

        while i < len(chunks) - 1:
            current_start, current_text, current_tokens = chunks[i]
            next_start, next_text, next_tokens = chunks[i + 1]

            # Calculate token count for combined text only if needed
            combined_text = current_text + next_text
            combined_tokens = get_token_count(combined_text)

            # If combining both chunks doesn't exceed max_tokens, merge them
            if combined_tokens <= max_tokens:
                optimized.append((current_start, combined_text, combined_tokens))
                i += 2  # Skip next chunk since we've merged it
            else:
                # Check if we can redistribute tokens more efficiently
                # Try to find optimal split point at a separator
                best_split_idx = None
                best_split_weight = -1

                for j in range(len(current_text) - 1, 0, -1):
                    char_weight = get_weight(current_text[j])

                    # For sentence terminators, include them in the first chunk
                    # We need to check if this is a valid split position - the character
                    # should end the current chunk rather than start the next one
                    if char_weight > best_split_weight:
                        split_pos = j + 1  # Include the separator in the first chunk

                        # Make sure we don't exceed the string length
                        if split_pos <= len(current_text):
                            # Check if redistributing at this point improves token usage
                            potential_first = current_text[:split_pos]
                            potential_next = current_text[split_pos:] + next_text

                            # Get token counts for potential chunks
                            potential_first_tokens = get_token_count(potential_first)
                            potential_next_tokens = get_token_count(potential_next)

                            # Ensure both chunks are valid
                            if (
                                potential_first_tokens <= max_tokens
                                and potential_next_tokens <= max_tokens
                            ):
                                best_split_idx = split_pos
                                best_split_weight = char_weight

                if best_split_idx is not None:
                    # Redistribute content between chunks
                    first_part = current_text[:best_split_idx]
                    first_tokens = get_token_count(first_part)
                    optimized.append((current_start, first_part, first_tokens))

                    second_part = current_text[best_split_idx:] + next_text
                    second_tokens = get_token_count(second_part)
                    chunks[i + 1] = (
                        current_start + best_split_idx,
                        second_part,
                        second_tokens,
                    )
                else:
                    # Cannot optimize further, keep original chunk
                    optimized.append((current_start, current_text, current_tokens))
                i += 1

        # Don't forget the last chunk if we didn't merge it
        if i < len(chunks):
            optimized.append(chunks[i])

        if len(optimized) and optimized[-1][1].strip() == "":
            optimized.pop()

        return optimized

    def split_by_weight(
        text: str, weight: int, start_idx: int
    ) -> List[Tuple[int, str, int]]:
        """Recursively split text at the given weight level."""
        chunks = []
        current_pos = 0
        current_chunk = []
        current_chunk_tokens = 0
        current_chunk_start = start_idx

        i = 0
        while i < len(text):
            char = text[i]
            char_weight = get_weight(char)

            # Consider splitting if we hit a separator of the current weight
            if char_weight >= weight:
                # Try to add the current segment to the chunk
                segment = text[
                    current_pos : i + 1
                ]  # Include the separator in this chunk
                segment_tokens = get_token_count(segment)

                if current_chunk_tokens + segment_tokens <= max_tokens:
                    current_chunk.append(segment)
                    current_chunk_tokens += segment_tokens
                    current_pos = i + 1  # Start next segment after the separator
                else:
                    # If adding this segment exceeds max_tokens, finalize current chunk
                    if current_chunk:
                        chunk_text = "".join(current_chunk)
                        chunks.append(
                            (current_chunk_start, chunk_text, current_chunk_tokens)
                        )
                        current_chunk_start += len(chunk_text)
                        current_chunk = []
                        current_chunk_tokens = 0

                    # If single segment exceeds max_tokens, try lower weight
                    if segment_tokens > max_tokens and weight > NO_WEIGHT:
                        sub_chunks = split_by_weight(
                            segment, weight - 1, current_chunk_start
                        )
                        chunks.extend(sub_chunks)
                        current_chunk_start += len(segment)
                        current_pos = i + 1
                    elif segment_tokens <= max_tokens:
                        current_chunk.append(segment)
                        current_chunk_tokens = segment_tokens
                        current_pos = i + 1
                    else:
                        raise ValueError(
                            "Cannot split segment within token limit; "
                            "consider increasing max_tokens"
                        )

            i += 1

        # Handle remaining text
        if current_pos < len(text):
            remaining = text[current_pos:]
            remaining_tokens = get_token_count(remaining)

            if current_chunk_tokens + remaining_tokens <= max_tokens:
                current_chunk.append(remaining)
                current_chunk_tokens += remaining_tokens
            else:
                if current_chunk:
                    chunk_text = "".join(current_chunk)
                    chunks.append(
                        (current_chunk_start, chunk_text, current_chunk_tokens)
                    )
                    current_chunk_start += len(chunk_text)

                if remaining_tokens > max_tokens and weight > NO_WEIGHT:
                    sub_chunks = split_by_weight(
                        remaining, weight - 1, current_chunk_start
                    )
                    chunks.extend(sub_chunks)
                elif remaining_tokens <= max_tokens:
                    chunks.append((current_chunk_start, remaining, remaining_tokens))
                else:
                    raise ValueError(
                        "Cannot split remaining text within token limit; "
                        "consider increasing max_tokens"
                    )

        # Add final chunk if exists
        if current_chunk:
            chunk_text = "".join(current_chunk)
            chunks.append((current_chunk_start, chunk_text, current_chunk_tokens))

        return chunks

    # First split with original algorithm
    initial_chunks = split_by_weight(text, PARAGRAPH_SEPARATOR_WEIGHT, 0)

    if optimize:
        # Then optimize to ensure maximum token utilization
        return optimize_chunks(initial_chunks)

    return initial_chunks
